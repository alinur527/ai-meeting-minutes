from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "samples" / "sample.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16_000
    duration_seconds = 2
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for index in range(sample_rate * duration_seconds):
            amplitude = (
                0
                if index > sample_rate
                else int(4000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            )
            wav.writeframesraw(struct.pack("<h", amplitude))
    print(output)


if __name__ == "__main__":
    main()
