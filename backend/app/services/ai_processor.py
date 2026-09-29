from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Self, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ..config import settings
from .remote_ai import request_processing


@dataclass(frozen=True)
class ProcessingParticipant:
    id: UUID
    name: str


class UnsupportedAIModeError(ValueError):
    """Raised when no processor is configured for the selected AI mode."""


class ProcessorSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpeakerResult(ProcessorSchema):
    label: str = Field(max_length=100)
    participant_id: UUID | None

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        label = value.strip()
        if not label:
            raise ValueError("Speaker label must not be empty")
        return label


class SegmentResult(ProcessorSchema):
    segment_index: int
    speaker_label: str
    start_ms: int = Field(ge=0)
    end_ms: int
    text: str

    @model_validator(mode="after")
    def validate_timing(self) -> Self:
        if self.end_ms < self.start_ms:
            raise ValueError("Segment end_ms must be greater than or equal to start_ms")
        return self


class ActionItemResult(ProcessorSchema):
    text: str
    assignee_id: UUID | None
    due_date: date | None
    deadline_text: str | None
    needs_review: bool
    review_reason: str | None
    source_segment_indexes: list[int]


class MeetingProcessingResult(ProcessorSchema):
    processing_mode: Literal["backend_mock", "ai_mock", "real"]
    summary: str
    speakers: list[SpeakerResult]
    segments: list[SegmentResult]
    action_items: list[ActionItemResult]

    @model_validator(mode="after")
    def validate_relations(self, info: ValidationInfo) -> Self:
        context = info.context or {}
        participant_ids = set(context.get("participant_ids", ()))

        speaker_labels = [speaker.label for speaker in self.speakers]
        if len(speaker_labels) != len(set(speaker_labels)):
            raise ValueError("Speaker labels must be unique")

        for speaker in self.speakers:
            if (
                speaker.participant_id is not None
                and speaker.participant_id not in participant_ids
            ):
                raise ValueError("Speaker participant_id does not belong to the meeting")

        segment_indexes = [segment.segment_index for segment in self.segments]
        if len(segment_indexes) != len(set(segment_indexes)):
            raise ValueError("Segment indexes must be unique")

        known_speaker_labels = set(speaker_labels)
        for segment in self.segments:
            if segment.speaker_label not in known_speaker_labels:
                raise ValueError("Segment speaker_label does not exist")

        known_segment_indexes = set(segment_indexes)
        for action_item in self.action_items:
            if (
                action_item.assignee_id is not None
                and action_item.assignee_id not in participant_ids
            ):
                raise ValueError("Action item assignee_id does not belong to the meeting")
            if len(action_item.source_segment_indexes) != len(
                set(action_item.source_segment_indexes)
            ):
                raise ValueError("Action item source segment indexes must be unique")
            if not set(action_item.source_segment_indexes).issubset(
                known_segment_indexes
            ):
                raise ValueError("Action item references an unknown segment")

        return self


def validate_result(
    result: Any,
    *,
    participant_ids: Sequence[UUID],
) -> MeetingProcessingResult:
    """Validate untrusted processor output, including meeting-scoped references."""

    return MeetingProcessingResult.model_validate(
        result,
        context={"participant_ids": set(participant_ids)},
    )


def _mock_result(participant_ids: Sequence[UUID]) -> dict[str, Any]:
    first_participant_id = participant_ids[0] if participant_ids else None
    second_participant_id = participant_ids[1] if len(participant_ids) > 1 else None

    return {
        "processing_mode": "backend_mock",
        "summary": "Обсудили подготовку проекта к хакатону.",
        "speakers": [
            {
                "label": "SPEAKER_00",
                "participant_id": first_participant_id,
            },
            {
                "label": "SPEAKER_01",
                "participant_id": second_participant_id,
            },
        ],
        "segments": [
            {
                "segment_index": 0,
                "speaker_label": "SPEAKER_00",
                "start_ms": 1000,
                "end_ms": 5000,
                "text": "Подготовим презентацию к завтра.",
            }
        ],
        "action_items": [
            {
                "text": "Подготовить презентацию",
                "assignee_id": first_participant_id,
                "due_date": None,
                "deadline_text": "завтра",
                "needs_review": True,
                "review_reason": "Mock result: срок требует проверки",
                "source_segment_indexes": [0],
            }
        ],
    }


def process_meeting(
    *,
    meeting_id: UUID,
    audio_path: str | None,
    meeting_date: date,
    timezone: str,
    participants: Sequence[ProcessingParticipant],
) -> MeetingProcessingResult:
    """Process one meeting using the explicitly configured processor."""

    participant_ids = [participant.id for participant in participants]
    if settings.ai_mode == "mock":
        raw_result = _mock_result(participant_ids)
    elif settings.ai_mode in {"http", "real"}:
        raw_result = request_processing(
            audio_path=audio_path,
            meta={
                "meeting_id": str(meeting_id),
                "meeting_date": meeting_date.isoformat(),
                "timezone": timezone,
                "participants": [
                    {"id": str(participant.id), "name": participant.name}
                    for participant in participants
                ],
            },
        )
    else:
        raise UnsupportedAIModeError(
            f"Unsupported AI_MODE: {settings.ai_mode!r}"
        )

    return validate_result(
        raw_result,
        participant_ids=participant_ids,
    )
