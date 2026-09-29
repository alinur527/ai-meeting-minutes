from __future__ import annotations

from pathlib import Path

from alem_contract.audio import EXTENSIONS, AudioValidationError, validate_header

from app.errors import ServiceError

ALLOWED_EXTENSIONS = EXTENSIONS


def validate_audio(filename: str | None, data: bytes, max_bytes: int) -> str:
    if not filename:
        raise ServiceError("AUDIO_FILENAME_MISSING", "audio filename is required")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ServiceError(
            "UNSUPPORTED_AUDIO_FORMAT",
            "supported audio formats are wav, mp3 and m4a",
            context={"filename": filename},
        )
    if not data:
        raise ServiceError("EMPTY_AUDIO", "uploaded audio file is empty")
    if len(data) > max_bytes:
        raise ServiceError(
            "AUDIO_TOO_LARGE",
            f"audio exceeds the configured limit of {max_bytes // (1024 * 1024)} MB",
            status_code=413,
        )
    try:
        validate_header(filename, data)
    except AudioValidationError as exc:
        raise ServiceError("CORRUPTED_AUDIO", str(exc)) from exc
    return suffix
