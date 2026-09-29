"""Real ASR only. This does not certify diarization, LLM, or the full real pipeline."""

import argparse
import json
from pathlib import Path

from alem_contract.audio import inspect_audio

from app.config import Settings
from app.pipeline.asr import FasterWhisperASR

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("audio", type=Path)
parser.add_argument("--synthetic", action="store_true")
parser.add_argument("--expected-word", action="append", default=[])
args = parser.parse_args()
settings = Settings.from_env()
inspect_audio(
    args.audio,
    max_bytes=settings.max_audio_mb * 1024 * 1024,
    max_seconds=settings.max_audio_seconds,
)
result = FasterWhisperASR(settings).transcribe(args.audio)
text = " ".join(segment.text for segment in result.segments).casefold().replace("ё", "е")
missing = [word for word in args.expected_word if word.casefold().replace("ё", "е") not in text]
report = {
    "stage": "ASR_ONLY",
    "synthetic": args.synthetic,
    "model": settings.asr_model,
    "device": settings.asr_device,
    "language": result.language,
    "segments": len(result.segments),
    "duration_ms": result.duration_ms,
    "expected_words": len(args.expected_word),
    "missing_words": missing,
}
print(json.dumps(report, ensure_ascii=False))
if missing:
    raise SystemExit(1)
