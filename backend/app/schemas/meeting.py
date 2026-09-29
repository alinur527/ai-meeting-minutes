from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


MeetingStatus = Literal["queued", "running", "completed", "failed"]


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParticipantCreate(ApiSchema):
    name: str = Field(max_length=255)

    @field_validator("name")
    @classmethod
    def strip_and_validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Participant name must not be empty")
        return name


class MeetingCreateResponse(ApiSchema):
    id: UUID
    status: MeetingStatus


class MeetingListItem(ApiSchema):
    id: UUID
    title: str
    started_at: datetime
    status: MeetingStatus
    confirmed_at: datetime | None


class MeetingListResponse(ApiSchema):
    items: list[MeetingListItem]


class ParticipantResponse(ApiSchema):
    id: UUID
    name: str


class SpeakerResponse(ApiSchema):
    label: str
    participant_id: UUID | None


class SegmentResponse(ApiSchema):
    id: UUID
    speaker: str | None
    start_ms: int
    end_ms: int
    text: str


class ActionItemResponse(ApiSchema):
    id: UUID
    text: str
    assignee_id: UUID | None
    due_date: date | None
    needs_review: bool
    review_reason: str | None
    deadline_text: str | None = None
    source_segment_ids: list[UUID]


class MeetingDetailResponse(ApiSchema):
    id: UUID
    title: str
    started_at: datetime
    timezone: str
    status: MeetingStatus
    error: str | None
    confirmed_at: datetime | None
    summary: str | None
    processing_mode: str | None = None
    processing_stage: str = "queued"
    duration_ms: int | None = None
    participants: list[ParticipantResponse]
    speakers: list[SpeakerResponse]
    segments: list[SegmentResponse]
    action_items: list[ActionItemResponse]
