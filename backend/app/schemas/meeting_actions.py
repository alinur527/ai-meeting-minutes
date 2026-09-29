from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ActionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskUpdateRequest(ActionSchema):
    text: str | None = None
    assignee_id: UUID | None = None
    due_date: date | None = None
    reviewed: bool = False


class TaskUpdateResponse(ActionSchema):
    id: UUID
    text: str
    assignee_id: UUID | None
    due_date: date | None
    needs_review: bool
    review_reason: str | None
    deadline_text: str | None = None
    source_segment_ids: list[UUID]


class SpeakerMappingRequest(ActionSchema):
    speaker: str
    participant_id: UUID | None


class SpeakerMappingsRequest(ActionSchema):
    mappings: list[SpeakerMappingRequest]


class SpeakerMappingResponse(ActionSchema):
    label: str
    participant_id: UUID | None


class SpeakerMappingsResponse(ActionSchema):
    speakers: list[SpeakerMappingResponse]


class MeetingConfirmResponse(ActionSchema):
    id: UUID
    confirmed_at: datetime
