import io
import json
import threading
import wave
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from alem_contract.audio import AudioValidationError, inspect_audio
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ServiceError
from app.main import create_app
from app.pipeline.asr import FasterWhisperASR
from app.pipeline.dates import resolve_due_date
from app.pipeline.llm import OllamaExtractor
from app.pipeline.mock import mock_response
from app.schemas import MeetingMeta, TranscriptSegment


def test_silence_has_explicit_error():
    asr = FasterWhisperASR(Settings.from_env())
    asr._model = SimpleNamespace(
        transcribe=lambda *a, **k: ([], SimpleNamespace(duration=1, language="ru"))
    )
    with pytest.raises(ServiceError) as caught:
        asr.transcribe("unused.wav")
    assert caught.value.code == "EMPTY_TRANSCRIPT"


def test_native_mkl_allocation_failure_is_reported_as_resource_limit():
    asr = FasterWhisperASR(Settings.from_env())

    def fail(*args, **kwargs):
        raise RuntimeError("mkl_malloc: failed to allocate memory")

    asr._model = SimpleNamespace(transcribe=fail)
    with pytest.raises(ServiceError) as caught:
        asr.transcribe("unused.wav")
    assert caught.value.code == "RESOURCE_LIMIT"
    assert caught.value.status_code == 503


def test_real_readiness_requires_available_models(monkeypatch):
    settings = replace(Settings.from_env(), mode="real", internal_token="test-token")
    app = create_app(settings)
    monkeypatch.setattr(app.state.pipeline.extractor, "ensure_model_available", lambda: None)

    def missing():
        raise ServiceError("ASR_MODEL_UNAVAILABLE", "No model", status_code=503)

    monkeypatch.setattr(app.state.pipeline.asr, "_load", missing)
    with pytest.raises(ServiceError):
        with TestClient(app):
            pytest.fail("startup must not report readiness")
    assert not app.state.ready


@pytest.mark.parametrize(
    "failure", ["unavailable", "invalid_json", "invented_deadline", "missing_evidence"]
)
def test_llm_failure_is_safe_and_bounded(monkeypatch, failure):
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        if failure == "unavailable":
            raise httpx.ConnectError("test")
        content = (
            "not json"
            if failure == "invalid_json"
            else json.dumps(
                {
                    "summary": "Result",
                    "action_items": [
                        {
                            "text": "Отчёт",
                            "due_text_raw": None if failure == "missing_evidence" else "завтра",
                            "evidence_segment_ids": [] if failure == "missing_evidence" else [0],
                        }
                    ],
                }
            )
        )
        return httpx.Response(
            200,
            json={"message": {"content": content}},
            request=httpx.Request("POST", "http://local/api/chat"),
        )

    monkeypatch.setattr("app.pipeline.llm.httpx.post", request)
    extractor = OllamaExtractor(replace(Settings.from_env(), llm_retries=1))
    with pytest.raises(ServiceError) as caught:
        extractor.extract(
            [
                TranscriptSegment(
                    id=0, start_ms=0, end_ms=1000, speaker="SPEAKER_00", text="Подготовить отчёт"
                )
            ],
            MeetingMeta(meeting_id="test", meeting_date="2026-09-25", timezone="UTC"),
        )
    assert caught.value.status_code == (503 if failure == "unavailable" else 422)
    assert len(calls) == (1 if failure == "unavailable" else 2)
    if failure == "invented_deadline":
        assert "exact quote" in calls[1]["json"]["messages"][-1]["content"]
    if failure == "missing_evidence":
        assert "nonempty evidence_segment_ids" in calls[1]["json"]["messages"][-1]["content"]


def test_llm_generation_constrains_nullable_references_inside_anyof(monkeypatch):
    def request(*args, **kwargs):
        schema = kwargs["json"]["format"]["$defs"]["ExtractedActionItem"]
        fields = schema["properties"]
        assert fields["assignee_participant_id"] == {"type": "null"}
        assert fields["assignee_speaker_label"] == {
            "anyOf": [{"type": "string", "enum": ["SPEAKER_00"]}, {"type": "null"}]
        }
        assert fields["evidence_segment_ids"]["items"]["enum"] == [0]
        assert fields["evidence_segment_ids"]["minItems"] == 1
        return httpx.Response(
            200,
            json={"message": {"content": '{"summary":"Обсуждение","action_items":[]}'}},
            request=httpx.Request("POST", "http://local/api/chat"),
        )

    monkeypatch.setattr("app.pipeline.llm.httpx.post", request)
    result = OllamaExtractor(Settings.from_env()).extract(
        [TranscriptSegment(id=0, start_ms=0, end_ms=1000, speaker="SPEAKER_00", text="Доклад")],
        MeetingMeta(meeting_id="test", meeting_date="2026-09-25", timezone="UTC"),
    )
    assert result.action_items == []


def test_memory_failure_releases_inference_lock(monkeypatch):
    from test_api import meta_payload, wav_bytes

    settings = replace(Settings.from_env(), mode="mock", internal_token="test-token")
    app = create_app(settings)

    def fail(*_):
        raise MemoryError()

    monkeypatch.setattr(app.state.pipeline, "process", fail)
    with TestClient(app, headers={"X-Internal-Token": "test-token"}) as client:
        args = {
            "files": {"audio": ("test.wav", wav_bytes())},
            "data": {"meta": json.dumps(meta_payload())},
        }
        assert client.post("/internal/process", **args).status_code == 422
        monkeypatch.setattr(
            app.state.pipeline, "process", lambda path, meta: mock_response(meta, settings)
        )
        assert client.post("/internal/process", **args).status_code == 200


@pytest.mark.parametrize(
    "phrase", ["к следующей пятнице", "келесі жұма", "на следующей неделе", "келесі апта"]
)
def test_ambiguous_deadline_preserves_unknown(phrase):
    assert resolve_due_date(phrase, date(2026, 9, 23)) is None


def test_long_transcript_is_rejected_before_llm(monkeypatch):
    extractor = OllamaExtractor(replace(Settings.from_env(), llm_max_input_bytes=1000))
    monkeypatch.setattr(
        "app.pipeline.llm.httpx.post", lambda *a, **k: pytest.fail("must not send truncated input")
    )
    segment = TranscriptSegment(
        id=0, start_ms=0, end_ms=1000, speaker="SPEAKER_00", text="Речь " * 1000
    )
    meta = MeetingMeta(meeting_id="test", meeting_date="2026-09-25", timezone="UTC")
    with pytest.raises(ServiceError) as error:
        extractor.extract([segment], meta)
    assert error.value.code == "TRANSCRIPT_TOO_LONG"


def test_decode_full_audio_and_duration_limit(tmp_path):
    path = tmp_path / "test.wav"
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0\0" * 32000)
    assert inspect_audio(path, max_bytes=100000, max_seconds=3).duration_ms == 2000
    with pytest.raises(AudioValidationError):
        inspect_audio(path, max_bytes=100000, max_seconds=1)
    path.write_bytes(b"RIFF0000WAVEbroken")
    with pytest.raises(AudioValidationError):
        inspect_audio(path, max_bytes=100000, max_seconds=3)


def test_token_required_and_concurrent_model_use_is_serialized(monkeypatch):
    settings = replace(Settings.from_env(), mode="mock", internal_token="test-token")
    app = create_app(settings)
    entered, release = threading.Event(), threading.Event()

    def slow_process(path, meta):
        entered.set()
        assert release.wait(5)
        return mock_response(meta, settings)

    monkeypatch.setattr(app.state.pipeline, "process", slow_process)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0\0" * 16000)
    files = {"audio": ("test.wav", buffer.getvalue(), "audio/wav")}
    data = {"meta": '{"meeting_id":"test","meeting_date":"2026-09-25","timezone":"UTC"}'}
    with TestClient(app) as client:
        assert client.post("/internal/process", files=files, data=data).status_code == 401
        assert client.get("/ready", headers={"X-Internal-Token": "test-token"}).status_code == 200
        results = []
        thread = threading.Thread(
            target=lambda: results.append(
                client.post(
                    "/internal/process",
                    files=files,
                    data=data,
                    headers={"X-Internal-Token": "test-token"},
                )
            )
        )
        thread.start()
        assert entered.wait(5)
        try:
            assert (
                client.post(
                    "/internal/process",
                    files=files,
                    data=data,
                    headers={"X-Internal-Token": "test-token"},
                ).status_code
                == 503
            )
        finally:
            release.set()
            thread.join(5)
        assert results[0].status_code == 200
