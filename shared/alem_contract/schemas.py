from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Participant(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("participant name is blank")
        return value.strip()


class MeetingMeta(StrictModel):
    meeting_id: str = Field(min_length=1, max_length=256)
    meeting_date: date
    timezone: str
    participants: list[Participant] = Field(default_factory=list, max_length=200)

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def participant_ids_are_unique(self) -> MeetingMeta:
        ids = [participant.id for participant in self.participants]
        if len(ids) != len(set(ids)):
            raise ValueError("participant ids must be unique")
        return self


class TranscriptSegment(StrictModel):
    id: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    speaker: str = Field(pattern=r"^SPEAKER_\d{2,}$")
    text: str

    @model_validator(mode="after")
    def end_is_after_start(self) -> TranscriptSegment:
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be greater than or equal to start_ms")
        return self


class SpeakerMatch(StrictModel):
    participant_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ActionItem(StrictModel):
    id: int = Field(ge=0)
    text: str = Field(min_length=1)
    assignee_participant_id: str | None = None
    assignee_speaker_label: str | None = None
    due_date: date | None = None
    due_text_raw: str | None = None
    evidence_segment_ids: list[int] = Field(default_factory=list)
    review_reason: str | None = None


class ProcessingMeta(StrictModel):
    mode: Literal["mock", "real"]
    asr_model: str
    diarization_model: str
    processed_at: datetime
    model_version: str


class ProcessResponse(StrictModel):
    meeting_id: str
    status: Literal["ok"]
    language_detected: str
    duration_ms: int = Field(ge=0)
    segments: list[TranscriptSegment]
    speakers: dict[str, SpeakerMatch]
    summary: str
    action_items: list[ActionItem]
    processing_meta: ProcessingMeta

    @model_validator(mode="after")
    def references_exist(self) -> ProcessResponse:
        ids = {segment.id for segment in self.segments}
        if len(ids) != len(self.segments):
            raise ValueError("duplicate segment ids")
        if len({action.id for action in self.action_items}) != len(self.action_items):
            raise ValueError("duplicate action ids")
        for segment in self.segments:
            if (
                segment.speaker not in self.speakers
                or segment.end_ms > self.duration_ms
            ):
                raise ValueError("invalid segment speaker or duration")
        for action in self.action_items:
            if action.assignee_speaker_label not in set(self.speakers) | {None}:
                raise ValueError("unknown action speaker")
            if not set(action.evidence_segment_ids).issubset(ids):
                raise ValueError("unknown evidence segment")
            if len(set(action.evidence_segment_ids)) != len(
                action.evidence_segment_ids
            ):
                raise ValueError("duplicate evidence segment")
        return self

    def validate_participants(self, participant_ids: set[str]) -> None:
        references = [speaker.participant_id for speaker in self.speakers.values()]
        references += [action.assignee_participant_id for action in self.action_items]
        if not set(references).issubset(participant_ids | {None}):
            raise ValueError("unknown participant reference")


class ExtractedActionItem(StrictModel):
    text: str = Field(min_length=1)
    assignee_participant_id: str | None = None
    assignee_speaker_label: str | None = None
    due_text_raw: str | None = None
    evidence_segment_ids: list[int] = Field(default_factory=list)


class LLMExtraction(StrictModel):
    summary: str
    action_items: list[ExtractedActionItem] = Field(default_factory=list)
