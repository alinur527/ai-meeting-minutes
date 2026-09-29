from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.errors import ServiceError
from app.pipeline.memory import release_cpu_memory


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    start_ms: int
    end_ms: int
    speaker: str


class PyannoteDiarizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pipeline: Any | None = None

    def _load(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        cache_dir = Path(
            os.environ.setdefault(
                "PYANNOTE_CACHE",
                str(
                    Path(os.environ.get("HF_HOME", self.settings.model_dir / "huggingface"))
                    / "hub"
                ),
            )
        )
        try:
            import torch
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise ServiceError(
                "DIARIZATION_DEPENDENCY_MISSING",
                "pyannote.audio is not installed; install the 'ml' dependency group",
                status_code=503,
            ) from exc

        model_ref = self.settings.diarization_model
        model_path = Path(model_ref)
        is_explicit_path = model_path.is_absolute() or model_ref.endswith((".yaml", ".yml"))
        if is_explicit_path and not model_path.exists():
            raise ServiceError(
                "DIARIZATION_MODEL_UNAVAILABLE",
                f"local diarization configuration not found: {model_path}",
                status_code=503,
            )
        try:
            self._pipeline = Pipeline.from_pretrained(
                str(model_path) if is_explicit_path else model_ref,
                cache_dir=cache_dir,
            )
            if self._pipeline is None:
                raise RuntimeError("Diarization model is unavailable or access is not granted")
            if self.settings.diarization_device == "cuda" or (
                self.settings.diarization_device == "auto" and torch.cuda.is_available()
            ):
                self._pipeline.to(torch.device("cuda"))
        except Exception as exc:
            raise ServiceError(
                "DIARIZATION_MODEL_UNAVAILABLE",
                f"cannot load local diarization model: {exc}",
                status_code=503,
            ) from exc
        return self._pipeline

    def unload(self) -> None:
        self._pipeline = None
        release_cpu_memory()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def diarize(self, audio_path: Path) -> list[SpeakerTurn]:
        try:
            output = self._load()(str(audio_path))
            annotation = getattr(output, "speaker_diarization", output)
            turns = [
                SpeakerTurn(
                    start_ms=max(0, round(turn.start * 1000)),
                    end_ms=max(0, round(turn.end * 1000)),
                    speaker=str(speaker),
                )
                for turn, _, speaker in annotation.itertracks(yield_label=True)
            ]
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(
                "DIARIZATION_FAILED", f"speaker diarization failed: {exc}", status_code=422
            ) from exc
        if not turns:
            raise ServiceError(
                "DIARIZATION_EMPTY", "diarization found no speaker turns", status_code=422
            )
        return normalize_speaker_labels(turns)


def normalize_speaker_labels(turns: list[SpeakerTurn]) -> list[SpeakerTurn]:
    labels: dict[str, str] = {}
    normalized: list[SpeakerTurn] = []
    for turn in sorted(turns, key=lambda item: (item.start_ms, item.end_ms)):
        labels.setdefault(turn.speaker, f"SPEAKER_{len(labels):02d}")
        normalized.append(SpeakerTurn(turn.start_ms, turn.end_ms, labels[turn.speaker]))
    return normalized
