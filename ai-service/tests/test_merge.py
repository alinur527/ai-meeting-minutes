from app.pipeline.asr import ASRSegment
from app.pipeline.diarization import SpeakerTurn
from app.pipeline.merge import merge_asr_with_speakers


def test_assigns_speaker_with_greatest_overlap() -> None:
    segments = [ASRSegment(0, 2000, "Первый"), ASRSegment(2000, 4000, "Второй")]
    turns = [SpeakerTurn(0, 1500, "SPEAKER_00"), SpeakerTurn(1500, 4000, "SPEAKER_01")]
    merged = merge_asr_with_speakers(segments, turns)
    assert [segment.speaker for segment in merged] == ["SPEAKER_00", "SPEAKER_01"]
