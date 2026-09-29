from __future__ import annotations

from app.pipeline.asr import ASRSegment
from app.pipeline.diarization import SpeakerTurn
from app.schemas import TranscriptSegment


def merge_asr_with_speakers(
    asr_segments: list[ASRSegment], turns: list[SpeakerTurn]
) -> list[TranscriptSegment]:
    """Assign each ASR segment to the speaker with the greatest time overlap."""
    merged: list[TranscriptSegment] = []
    for index, segment in enumerate(asr_segments):
        best_speaker = "SPEAKER_00"
        best_overlap = 0
        best_distance = float("inf")
        midpoint = (segment.start_ms + segment.end_ms) / 2
        for turn in turns:
            overlap = max(
                0,
                min(segment.end_ms, turn.end_ms) - max(segment.start_ms, turn.start_ms),
            )
            distance = (
                0
                if turn.start_ms <= midpoint <= turn.end_ms
                else min(abs(midpoint - turn.start_ms), abs(midpoint - turn.end_ms))
            )
            if overlap > best_overlap or (overlap == best_overlap and distance < best_distance):
                best_overlap = overlap
                best_distance = distance
                best_speaker = turn.speaker
        merged.append(
            TranscriptSegment(
                id=index,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                speaker=best_speaker,
                text=segment.text,
            )
        )
    return merged
