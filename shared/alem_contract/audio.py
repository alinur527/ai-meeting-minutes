import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import av

MEDIA = json.loads(files("alem_contract").joinpath("media.json").read_text())
EXTENSIONS = frozenset(MEDIA["extensions"])


class AudioValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AudioInfo:
    duration_ms: int


def validate_header(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in EXTENSIONS:
        raise AudioValidationError("Поддерживаются WAV, MP3 и M4A")
    valid = {
        ".wav": len(data) >= 12
        and data[:4] in {b"RIFF", b"RF64"}
        and data[8:12] == b"WAVE",
        ".mp3": data[:3] == b"ID3"
        or (len(data) >= 2 and data[0] == 255 and data[1] & 224 == 224),
        ".m4a": len(data) >= 12 and data[4:8] == b"ftyp",
    }[suffix]
    if not valid:
        raise AudioValidationError("Содержимое не соответствует формату аудиофайла")
    return suffix


def inspect_audio(path: Path, *, max_bytes: int, max_seconds: int) -> AudioInfo:
    """Decode the entire first audio stream, stopping as soon as a bound is exceeded."""
    if path.suffix.lower() not in EXTENSIONS:
        raise AudioValidationError("Поддерживаются WAV, MP3 и M4A")
    if not 0 < path.stat().st_size <= max_bytes:
        raise AudioValidationError("Аудиофайл пуст или превышает допустимый размер")
    with path.open("rb") as source:
        header = source.read(64)
    validate_header(path.name, header)
    if path.suffix.lower() == ".wav" and header[:4] == b"RIFF":
        if int.from_bytes(header[4:8], "little") + 8 > path.stat().st_size:
            raise AudioValidationError("WAV-файл обрезан")
    duration = 0.0
    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise AudioValidationError("В файле нет аудиодорожки")
            stream = container.streams.audio[0]
            if stream.duration is not None and stream.time_base is not None:
                if float(stream.duration * stream.time_base) > max_seconds:
                    raise AudioValidationError(f"Запись длиннее {max_seconds} секунд")
            for frame in container.decode(stream):
                duration += frame.samples / frame.sample_rate
                if duration > max_seconds:
                    raise AudioValidationError(f"Запись длиннее {max_seconds} секунд")
    except AudioValidationError:
        raise
    except (av.FFmpegError, ValueError, OSError) as exc:
        raise AudioValidationError("Аудиофайл повреждён или не декодируется") from exc
    if duration <= 0:
        raise AudioValidationError("Аудиодорожка пуста")
    return AudioInfo(duration_ms=round(duration * 1000))
