"""HTTP transport and adapter for the separately deployed Hackalem AI service."""

import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError
from alem_contract.schemas import ProcessResponse

from ..config import settings

AI_AUDIO_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
SAFE_AI_ERRORS = {
    "TRANSCRIPT_TOO_LONG": "Транскрипт слишком длинный для модели. Разделите запись на части.",
    "EMPTY_TRANSCRIPT": "В записи не удалось обнаружить речь. Проверьте аудио.",
    "CORRUPTED_AUDIO": "Не удалось прочитать аудиозапись. Загрузите корректный WAV, MP3 или M4A.",
    "DIARIZATION_EMPTY": "Не удалось различить говорящих. Проверьте качество записи.",
    "LLM_EXTRACTION_FAILED": "Модель не смогла надёжно выделить поручения. Можно повторить обработку.",
    "RESOURCE_LIMIT": "ИИ не хватает памяти. Освободите ресурсы или сократите запись.",
    "BUSY": "ИИ обрабатывает другую запись. Повторим попытку автоматически.",
    "OLLAMA_UNAVAILABLE": "Локальная языковая модель недоступна. Повторим попытку автоматически.",
}


def _known_error(response: httpx.Response) -> str | None:
    """Read a bounded error envelope; never propagate raw model/server messages."""
    body = bytearray()
    for chunk in response.iter_bytes(chunk_size=4096):
        if len(body) + len(chunk) > 16384:
            return None
        body.extend(chunk)
    try:
        payload = json.loads(body)
        code = payload["error"]["code"]
        return SAFE_AI_ERRORS.get(code) if isinstance(code, str) else None
    except (ValueError, KeyError, TypeError):
        return None


class AIServiceError(RuntimeError):
    """Safe user message and retry classification."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def adapt_response(payload: Any, *, meeting_id: str) -> dict[str, Any]:
    result = ProcessResponse.model_validate(payload)
    if result.meeting_id != meeting_id:
        raise AIServiceError("ИИ вернул результат другого совещания.")
    if result.processing_meta.mode != settings.ai_expected_mode:
        raise AIServiceError(
            "Режим AI-сервиса не совпадает с AI_EXPECTED_MODE. Результат не сохранён."
        )

    actions = []
    for action in result.action_items:
        if (
            action.assignee_speaker_label is not None
            and action.assignee_speaker_label not in result.speakers
        ):
            raise AIServiceError("ИИ вернул поручение с неизвестным спикером.")
        assignee_id = action.assignee_participant_id
        if assignee_id is None and action.assignee_speaker_label is not None:
            assignee_id = result.speakers[action.assignee_speaker_label].participant_id
        reasons = [action.review_reason] if action.review_reason else []
        if assignee_id is None:
            reasons.append("Не определён ответственный")
        if action.due_date is None:
            reasons.append(
                "Срок требует проверки" if action.due_text_raw else "Срок не указан"
            )
        if not action.evidence_segment_ids:
            reasons.append("Нет ссылки на фрагмент записи")
        actions.append(
            {
                "text": action.text,
                "assignee_id": assignee_id,
                "due_date": action.due_date,
                "deadline_text": action.due_text_raw,
                "needs_review": bool(reasons),
                "review_reason": "; ".join(reasons) or None,
                "source_segment_indexes": action.evidence_segment_ids,
            }
        )

    return {
        "summary": result.summary,
        "processing_mode": "ai_mock"
        if result.processing_meta.mode == "mock"
        else "real",
        "speakers": [
            {"label": label, "participant_id": speaker.participant_id}
            for label, speaker in result.speakers.items()
        ],
        "segments": [
            {
                "segment_index": segment.id,
                "speaker_label": segment.speaker,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": segment.text,
            }
            for segment in result.segments
        ],
        "action_items": actions,
    }


def request_processing(
    *, audio_path: str | None, meta: dict[str, Any]
) -> dict[str, Any]:
    if not audio_path or not Path(audio_path).is_file():
        raise AIServiceError(
            "Аудиофайл недоступен worker. Проверьте STORAGE_DIR и файл."
        )
    path = Path(audio_path)
    media_type = AI_AUDIO_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise AIServiceError(
            "ИИ принимает WAV, MP3 и M4A. Загрузите запись в одном из этих форматов."
        )

    headers = {}
    if settings.ai_internal_token and settings.ai_internal_token.get_secret_value():
        headers["X-Internal-Token"] = settings.ai_internal_token.get_secret_value()
    url = str(settings.ai_base_url).rstrip("/") + "/internal/process"
    timeout = httpx.Timeout(settings.ai_timeout_seconds, connect=10.0)
    try:
        # Send bytes, not a local path: the AI laptop has no access to backend storage.
        # Ignore OS proxy variables for this private service-to-service connection.
        with (
            path.open("rb") as audio,
            httpx.Client(timeout=timeout, trust_env=False) as client,
        ):
            with client.stream(
                "POST",
                url,
                headers=headers,
                files={"audio": (path.name, audio, media_type)},
                data={"meta": json.dumps(meta, ensure_ascii=False)},
            ) as response:
                if response.is_error:
                    message = _known_error(response)
                    if message:
                        raise AIServiceError(
                            message,
                            retryable=response.status_code
                            in {408, 429, 500, 502, 503, 504},
                        )
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise AIServiceError("Ответ ИИ превышает допустимый размер")
                    body.extend(chunk)
    except httpx.TimeoutException as exc:
        raise AIServiceError(
            "ИИ не ответил вовремя. Повторим обработку.", retryable=True
        ) from exc
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        messages = {
            401: "ИИ отклонил токен. Сверьте AI_INTERNAL_TOKEN и INTERNAL_TOKEN.",
            404: "Не найден /internal/process. Проверьте AI_BASE_URL и порт ИИ.",
            413: "Аудио превышает MAX_AUDIO_MB на стороне ИИ.",
            422: "ИИ отклонил аудио или метаданные. Проверьте файл и логи ИИ.",
        }
        raise AIServiceError(
            messages.get(code, f"Ошибка ИИ HTTP {code}. Проверьте состояние сервиса."),
            retryable=code in {408, 429, 500, 502, 503, 504},
        ) from exc
    except httpx.RequestError as exc:
        raise AIServiceError(
            "Нет связи с ИИ. Проверьте AI_BASE_URL, сеть, порт и запуск сервиса.",
            retryable=True,
        ) from exc

    try:
        raw = json.loads(body)
        parsed = ProcessResponse.model_validate(raw)
        parsed.validate_participants(
            {participant["id"] for participant in meta["participants"]}
        )
        return adapt_response(raw, meeting_id=meta["meeting_id"])
    except (ValueError, ValidationError) as exc:
        raise AIServiceError(
            "ИИ вернул некорректный JSON или несовместимый формат ответа."
        ) from exc
