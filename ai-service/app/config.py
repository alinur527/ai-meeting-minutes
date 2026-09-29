from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    mode: str
    model_dir: Path
    asr_model: str
    asr_device: str
    asr_compute_type: str
    diarization_model: str
    ollama_url: str
    llm_model: str
    llm_retries: int
    max_audio_mb: int
    internal_token: str | None
    hf_offline: bool
    low_memory_mode: bool
    model_version: str
    max_audio_seconds: int = 1800
    llm_max_input_bytes: int = 16000
    llm_context_tokens: int = 32768
    diarization_device: str = "auto"

    @classmethod
    def from_env(cls) -> Settings:
        mode = os.getenv("AI_MODE", "real").strip().lower()
        if mode not in {"mock", "real"}:
            raise ValueError("AI_MODE must be either 'mock' or 'real'")
        return cls(
            mode=mode,
            model_dir=Path(os.getenv("MODEL_DIR", "/models")),
            asr_model=os.getenv("ASR_MODEL", "Systran/faster-whisper-large-v3"),
            asr_device=os.getenv("ASR_DEVICE", "auto"),
            asr_compute_type=os.getenv("ASR_COMPUTE_TYPE", "auto"),
            diarization_model=os.getenv("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"),
            ollama_url=os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/"),
            llm_model=os.getenv("LLM_MODEL", "qwen2.5:7b-instruct-q4_K_M"),
            llm_retries=max(0, int(os.getenv("LLM_RETRIES", "2"))),
            max_audio_mb=min(200, max(1, int(os.getenv("MAX_AUDIO_MB", "200")))),
            internal_token=os.getenv("INTERNAL_TOKEN") or None,
            hf_offline=_as_bool(os.getenv("HF_HUB_OFFLINE"), True),
            low_memory_mode=_as_bool(os.getenv("LOW_MEMORY_MODE"), False),
            model_version=os.getenv("MODEL_VERSION", "hackalem-ai-0.1.0"),
            max_audio_seconds=min(1800, max(1, int(os.getenv("MAX_AUDIO_SECONDS", "1800")))),
            llm_max_input_bytes=min(16000, max(1, int(os.getenv("LLM_MAX_INPUT_BYTES", "16000")))),
            llm_context_tokens=max(8192, int(os.getenv("LLM_CONTEXT_TOKENS", "32768"))),
            diarization_device=os.getenv("DIARIZATION_DEVICE", "auto"),
        )
