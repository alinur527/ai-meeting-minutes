from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.schemas import (
    ActionItem,
    MeetingMeta,
    ProcessingMeta,
    ProcessResponse,
    SpeakerMatch,
    TranscriptSegment,
)


def mock_response(meta: MeetingMeta, settings: Settings) -> ProcessResponse:
    assignee = meta.participants[0].id if meta.participants else None
    assignee_name = meta.participants[0].name if meta.participants else "участник"
    speaker_match = (
        SpeakerMatch(participant_id=assignee, confidence=0.99) if assignee else SpeakerMatch()
    )
    return ProcessResponse(
        meeting_id=meta.meeting_id,
        status="ok",
        language_detected="mixed-ru-kk",
        duration_ms=15_000,
        segments=[
            TranscriptSegment(
                id=0,
                start_ms=0,
                end_ms=5_400,
                speaker="SPEAKER_00",
                text=(f"Меня зовут {assignee_name}. Подготовлю финальную презентацию к пятнице."),
            ),
            TranscriptSegment(
                id=1,
                start_ms=5_500,
                end_ms=10_200,
                speaker="SPEAKER_01",
                text="Жақсы, нәтижені командаға жіберуді ұмытпаңыз.",
            ),
        ],
        speakers={"SPEAKER_00": speaker_match, "SPEAKER_01": SpeakerMatch()},
        summary="Команда согласовала подготовку и отправку финальной презентации.",
        action_items=[
            ActionItem(
                id=0,
                text="Подготовить финальную презентацию и отправить команде",
                assignee_participant_id=assignee,
                assignee_speaker_label="SPEAKER_00",
                due_date=_next_friday(meta.meeting_date),
                due_text_raw="к пятнице",
                evidence_segment_ids=[0, 1],
            )
        ],
        processing_meta=ProcessingMeta(
            mode="mock",
            asr_model="mock-asr",
            diarization_model="mock-diarization",
            processed_at=datetime.now(ZoneInfo(meta.timezone)),
            model_version=settings.model_version,
        ),
    )


def _next_friday(base):
    from app.pipeline.dates import resolve_due_date

    return resolve_due_date("к пятнице", base)
