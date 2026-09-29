from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.errors import ServiceError
from app.pipeline.memory import release_cpu_memory


@dataclass(frozen=True, slots=True)
class ASRSegment:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class ASRResult:
    segments: list[ASRSegment]
    language: str
    duration_ms: int


class FasterWhisperASR:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ServiceError(
                "ASR_DEPENDENCY_MISSING",
                "faster-whisper is not installed; install the 'ml' dependency group",
                status_code=503,
            ) from exc

        configured = self.settings.asr_model
        local_candidate = self.settings.model_dir / configured
        model_ref = str(local_candidate) if local_candidate.exists() else configured
        try:
            self._model = WhisperModel(
                model_ref,
                device=self.settings.asr_device,
                compute_type=self.settings.asr_compute_type,
                local_files_only=self.settings.hf_offline,
            )
        except Exception as exc:
            raise ServiceError(
                "ASR_MODEL_UNAVAILABLE",
                f"cannot load local ASR model '{model_ref}': {exc}",
                status_code=503,
            ) from exc
        return self._model

    def unload(self) -> None:
        self._model = None
        release_cpu_memory()

    def transcribe(self, audio_path: Path) -> ASRResult:
        model = self._load()
        try:
            raw_segments, info = model.transcribe(
                str(audio_path),
                language=None,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 350},
                condition_on_previous_text=True,
            )
            segments = [
                ASRSegment(
                    start_ms=max(0, round(segment.start * 1000)),
                    end_ms=max(0, round(segment.end * 1000)),
                    text=segment.text.strip(),
                )
                for segment in raw_segments
                if segment.text.strip()
            ]
        except (MemoryError, RuntimeError) as exc:
            if isinstance(exc, MemoryError) or "mkl_malloc: failed to allocate memory" in str(exc):
                raise ServiceError(
                    "RESOURCE_LIMIT",
                    "ASR ran out of memory while processing audio",
                    status_code=503,
                ) from exc
            raise ServiceError(
                "AUDIO_DECODE_FAILED",
                f"audio could not be decoded or transcribed: {exc}",
                status_code=422,
            ) from exc
        except Exception as exc:
            raise ServiceError(
                "AUDIO_DECODE_FAILED",
                f"audio could not be decoded or transcribed: {exc}",
                status_code=422,
            ) from exc

        if not segments:
            raise ServiceError(
                "EMPTY_TRANSCRIPT", "no speech was detected in the audio", status_code=422
            )
        duration_ms = round(float(getattr(info, "duration", segments[-1].end_ms / 1000)) * 1000)
        language = str(getattr(info, "language", "unknown"))
        return ASRResult(segments=segments, language=language, duration_ms=duration_ms)
