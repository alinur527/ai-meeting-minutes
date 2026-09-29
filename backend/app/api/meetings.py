import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload
from starlette.responses import FileResponse, StreamingResponse

from alem_contract.audio import EXTENSIONS, MEDIA, AudioValidationError, inspect_audio
from ..auth import Identity, current_user, consume_rate
from ..config import settings
from ..db import get_db
from ..services.remote_ai import AI_AUDIO_TYPES
from ..models import ActionItem, Job, Meeting, Participant, Segment, Speaker, User
from ..models.base import utc_now
from ..schemas.meeting_actions import (
    MeetingConfirmResponse,
    SpeakerMappingResponse,
    SpeakerMappingsRequest,
    SpeakerMappingsResponse,
    TaskUpdateRequest,
    TaskUpdateResponse,
)
from ..schemas.meeting import (
    ActionItemResponse,
    MeetingCreateResponse,
    MeetingDetailResponse,
    MeetingListItem,
    MeetingListResponse,
    ParticipantCreate,
    ParticipantResponse,
    SegmentResponse,
    SpeakerResponse,
)
from ..services.docx_export import (
    ExportSegment,
    ExportTask,
    MeetingExportData,
    build_meeting_docx,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["meetings"])

ALLOWED_EXTENSIONS = EXTENSIONS
UPLOAD_CHUNK_SIZE = 1024 * 1024
participants_adapter = TypeAdapter(list[ParticipantCreate])

AUDIO_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".ogg": "audio/ogg",
}
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _parse_started_at(value: str | None) -> datetime:
    if value is None:
        raise _bad_request("started_at is required")

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _bad_request(
            "started_at must be an ISO 8601 timezone-aware datetime"
        ) from exc

    if parsed.utcoffset() is None:
        raise _bad_request("started_at must include a timezone offset")
    return parsed


def _parse_timezone(value: str | None) -> str:
    if value is None:
        raise _bad_request("timezone is required")

    timezone_name = value.strip()
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise _bad_request("timezone must be a valid IANA timezone") from exc
    return timezone_name


def _parse_participants(value: str | None) -> list[ParticipantCreate]:
    if value is None:
        raise _bad_request("participants_json is required")

    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _bad_request("participants_json must be valid JSON") from exc

    if not isinstance(decoded, list):
        raise _bad_request("participants_json must be a JSON array")

    try:
        participants = participants_adapter.validate_python(decoded)
    except ValidationError as exc:
        raise _bad_request("participants_json contains invalid participants") from exc

    if not participants:
        raise _bad_request("At least one participant is required")
    return participants


def _remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.error("Could not remove uploaded file: %s", path)


def _save_upload(upload: UploadFile, destination: Path, max_bytes: int) -> None:
    total_bytes = 0
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            while chunk := upload.file.read(UPLOAD_CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="Uploaded file is too large",
                    )
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except HTTPException:
        _remove_file(destination)
        raise
    except OSError as exc:
        _remove_file(destination)
        logger.error("Could not save uploaded file: %s", destination)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save uploaded file",
        ) from exc


def _localized_started_at(meeting: Meeting) -> datetime:
    return meeting.started_at.astimezone(ZoneInfo(meeting.timezone))


def _to_list_item(meeting: Meeting) -> MeetingListItem:
    return MeetingListItem(
        id=meeting.id,
        title=meeting.title,
        started_at=_localized_started_at(meeting),
        status=meeting.status,
        confirmed_at=meeting.confirmed_at,
    )


def _to_detail(meeting: Meeting) -> MeetingDetailResponse:
    participants = sorted(
        meeting.participants, key=lambda item: (item.created_at, str(item.id))
    )
    speakers = sorted(meeting.speakers, key=lambda item: (item.label, str(item.id)))
    segments = sorted(
        meeting.segments, key=lambda item: (item.segment_index, str(item.id))
    )
    action_items = sorted(
        meeting.action_items, key=lambda item: (item.created_at, str(item.id))
    )

    return MeetingDetailResponse(
        id=meeting.id,
        title=meeting.title,
        started_at=_localized_started_at(meeting),
        timezone=meeting.timezone,
        status=meeting.status,
        error=meeting.error,
        confirmed_at=meeting.confirmed_at,
        summary=meeting.summary,
        processing_mode=meeting.processing_mode,
        processing_stage=meeting.processing_stage,
        duration_ms=meeting.duration_ms,
        participants=[
            ParticipantResponse(id=participant.id, name=participant.name)
            for participant in participants
        ],
        speakers=[
            SpeakerResponse(
                label=speaker.label,
                participant_id=speaker.participant_id,
            )
            for speaker in speakers
        ],
        segments=[
            SegmentResponse(
                id=segment.id,
                speaker=segment.speaker.label if segment.speaker is not None else None,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=segment.text,
            )
            for segment in segments
        ],
        action_items=[
            ActionItemResponse(
                id=action_item.id,
                text=action_item.text,
                assignee_id=action_item.assignee_id,
                due_date=action_item.due_date,
                needs_review=action_item.needs_review,
                review_reason=action_item.review_reason,
                deadline_text=action_item.deadline_text,
                source_segment_ids=[
                    segment.id
                    for segment in sorted(
                        action_item.source_segments,
                        key=lambda item: (item.segment_index, str(item.id)),
                    )
                ],
            )
            for action_item in action_items
        ],
    )


def _to_task_response(action_item: ActionItem) -> TaskUpdateResponse:
    return TaskUpdateResponse(
        deadline_text=action_item.deadline_text,
        id=action_item.id,
        text=action_item.text,
        assignee_id=action_item.assignee_id,
        due_date=action_item.due_date,
        needs_review=action_item.needs_review,
        review_reason=action_item.review_reason,
        source_segment_ids=[
            segment.id
            for segment in sorted(
                action_item.source_segments,
                key=lambda item: (item.segment_index, str(item.id)),
            )
        ],
    )


def _to_export_data(meeting: Meeting) -> MeetingExportData:
    participants = sorted(
        meeting.participants, key=lambda item: (item.created_at, str(item.id))
    )
    participant_names = {
        participant.id: participant.name for participant in participants
    }

    tasks = tuple(
        ExportTask(
            text=action_item.text,
            assignee=participant_names.get(action_item.assignee_id),
            due_date=action_item.due_date,
            deadline_text=action_item.deadline_text,
            review_reason=action_item.review_reason
            if action_item.needs_review
            else None,
        )
        for action_item in sorted(
            meeting.action_items, key=lambda item: (item.created_at, str(item.id))
        )
    )

    segments = []
    for segment in sorted(
        meeting.segments, key=lambda item: (item.segment_index, str(item.id))
    ):
        if segment.speaker is None:
            speaker_name = "Не указан"
        else:
            participant_name = participant_names.get(segment.speaker.participant_id)
            speaker_name = segment.speaker.label
            if participant_name is not None:
                speaker_name = f"{speaker_name} - {participant_name}"
        segments.append(
            ExportSegment(
                speaker=speaker_name,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=segment.text,
            )
        )

    return MeetingExportData(
        title=meeting.title,
        started_at=meeting.started_at,
        timezone=meeting.timezone,
        participants=tuple(participant.name for participant in participants),
        summary=meeting.summary,
        tasks=tasks,
        segments=tuple(segments),
        processing_mode=meeting.processing_mode,
    )


@router.post(
    "", response_model=MeetingCreateResponse, status_code=status.HTTP_202_ACCEPTED
)
def create_meeting(
    file: Annotated[UploadFile | None, File()] = None,
    title: Annotated[str | None, Form()] = None,
    started_at: Annotated[str | None, Form()] = None,
    timezone: Annotated[str | None, Form()] = None,
    participants_json: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    user: Identity = Depends(current_user),
) -> MeetingCreateResponse:
    if file is None:
        raise _bad_request("file is required")

    normalized_title = title.strip() if title is not None else ""
    if not normalized_title:
        raise _bad_request("title must not be empty")
    if len(normalized_title) > 255:
        raise _bad_request("title must not exceed 255 characters")

    parsed_started_at = _parse_started_at(started_at)
    timezone_name = _parse_timezone(timezone)
    participants = _parse_participants(participants_json)
    if len(participants) > MEDIA["max_participants"]:
        raise _bad_request("AI service supports at most 200 participants")

    extension = Path(file.filename or "").suffix.casefold()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file extension",
        )
    if settings.ai_mode != "mock" and extension not in AI_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="AI service supports WAV, MP3 and M4A; convert the recording before uploading",
        )

    consume_rate(
        db, f"upload:{user.id}", limit=settings.upload_limit_per_hour, seconds=3600
    )
    destination = Path(settings.storage_dir).resolve() / f"{uuid4()}{extension}"
    partial = destination.with_name(destination.stem + ".part" + extension)
    _save_upload(file, partial, settings.max_upload_mb * 1024 * 1024)
    try:
        audio_info = inspect_audio(
            partial,
            max_bytes=settings.max_upload_mb * 1024 * 1024,
            max_seconds=settings.max_audio_seconds,
        )
        os.replace(partial, destination)
    except AudioValidationError as exc:
        _remove_file(partial)
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        _remove_file(partial)
        raise

    meeting = Meeting(
        owner_id=user.id,
        duration_ms=audio_info.duration_ms,
        title=normalized_title,
        started_at=parsed_started_at,
        timezone=timezone_name,
        status="queued",
        audio_path=str(destination),
        participants=[
            Participant(name=participant.name) for participant in participants
        ],
        jobs=[Job(status="queued", attempts=0)],
    )

    try:
        with db.begin():
            db.scalar(select(User).where(User.id == user.id).with_for_update())
            active = db.scalar(
                select(func.count())
                .select_from(Meeting)
                .where(
                    Meeting.owner_id == user.id,
                    Meeting.status.in_(["queued", "running"]),
                )
            )
            if active >= settings.max_active_meetings:
                raise HTTPException(429, "Дождитесь завершения текущих записей")
            db.add(meeting)
    except HTTPException:
        _remove_file(destination)
        raise
    except Exception as exc:
        _remove_file(destination)
        logger.error("Could not create meeting in PostgreSQL")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create meeting",
        ) from exc

    return MeetingCreateResponse(id=meeting.id, status=meeting.status)


@router.get("", response_model=MeetingListResponse)
def list_meetings(
    db: Session = Depends(get_db),
    user: Identity = Depends(current_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> MeetingListResponse:
    try:
        meetings = db.scalars(
            select(Meeting)
            .where(Meeting.owner_id == user.id)
            .order_by(Meeting.started_at.desc(), Meeting.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    except SQLAlchemyError as exc:
        logger.error("Could not list meetings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not list meetings",
        ) from exc

    return MeetingListResponse(items=[_to_list_item(meeting) for meeting in meetings])


@router.get("/{meeting_id}", response_model=MeetingDetailResponse)
def get_meeting(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    user: Identity = Depends(current_user),
) -> MeetingDetailResponse:
    statement = (
        select(Meeting)
        .where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
        .options(
            selectinload(Meeting.participants),
            selectinload(Meeting.speakers),
            selectinload(Meeting.segments).joinedload(Segment.speaker),
            selectinload(Meeting.action_items).selectinload(ActionItem.source_segments),
        )
    )
    try:
        meeting = db.scalar(statement)
    except SQLAlchemyError as exc:
        logger.error("Could not load meeting %s", meeting_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load meeting",
        ) from exc

    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )

    return _to_detail(meeting)


@router.patch("/{meeting_id}/tasks/{task_id}", response_model=TaskUpdateResponse)
def update_task(
    meeting_id: UUID,
    task_id: UUID,
    request: TaskUpdateRequest,
    db: Session = Depends(get_db),
    user: Identity = Depends(current_user),
) -> TaskUpdateResponse:
    try:
        with db.begin():
            meeting = db.scalar(
                select(Meeting)
                .where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
                .with_for_update()
            )
            if meeting is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Meeting not found",
                )

            action_item = db.scalar(
                select(ActionItem)
                .where(
                    ActionItem.id == task_id,
                    ActionItem.meeting_id == meeting_id,
                )
                .options(selectinload(ActionItem.source_segments))
                .with_for_update()
            )
            if action_item is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Task not found",
                )

            if meeting.status != "completed":
                raise HTTPException(409, "Редактирование доступно после обработки")
            changed = False
            fields_set = request.model_fields_set

            if "text" in fields_set:
                if request.text is None or not request.text.strip():
                    raise _bad_request("text must not be empty")
                normalized_text = request.text.strip()
                if action_item.text != normalized_text:
                    action_item.text = normalized_text
                    changed = True

            if "assignee_id" in fields_set:
                if request.assignee_id is not None:
                    participant_id = db.scalar(
                        select(Participant.id).where(
                            Participant.id == request.assignee_id,
                            Participant.meeting_id == meeting_id,
                        )
                    )
                    if participant_id is None:
                        raise _bad_request("assignee_id must belong to this meeting")
                if action_item.assignee_id != request.assignee_id:
                    action_item.assignee_id = request.assignee_id
                    changed = True

            if "due_date" in fields_set and action_item.due_date != request.due_date:
                action_item.due_date = request.due_date
                changed = True

            if request.reviewed:
                action_item.needs_review = False
                action_item.review_reason = None
                changed = True
            elif changed:
                reasons = []
                if action_item.assignee_id is None:
                    reasons.append("Не определён ответственный")
                if action_item.due_date is None:
                    reasons.append("Срок требует проверки")
                if not action_item.source_segments:
                    reasons.append("Нет ссылки на фрагмент записи")
                action_item.needs_review = bool(reasons)
                action_item.review_reason = "; ".join(reasons) or None
            if changed and meeting.confirmed_at is not None:
                meeting.confirmed_at = None

            response = _to_task_response(action_item)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("Could not update task %s for meeting %s", task_id, meeting_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update task",
        ) from exc

    return response


@router.patch("/{meeting_id}/speakers", response_model=SpeakerMappingsResponse)
def update_speakers(
    meeting_id: UUID,
    request: SpeakerMappingsRequest,
    db: Session = Depends(get_db),
    user: Identity = Depends(current_user),
) -> SpeakerMappingsResponse:
    requested_labels = [mapping.speaker for mapping in request.mappings]
    if len(requested_labels) != len(set(requested_labels)):
        raise _bad_request("A speaker must not appear more than once")

    try:
        with db.begin():
            meeting = db.scalar(
                select(Meeting)
                .where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
                .with_for_update()
            )
            if meeting is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Meeting not found",
                )

            if meeting.status != "completed":
                raise HTTPException(409, "Дождитесь завершения обработки")
            speakers = db.scalars(
                select(Speaker)
                .where(Speaker.meeting_id == meeting_id)
                .order_by(Speaker.label, Speaker.id)
                .with_for_update()
            ).all()
            speakers_by_label = {speaker.label: speaker for speaker in speakers}

            unknown_labels = set(requested_labels) - set(speakers_by_label)
            if unknown_labels:
                raise _bad_request("speaker must belong to this meeting")

            requested_participant_ids = {
                mapping.participant_id
                for mapping in request.mappings
                if mapping.participant_id is not None
            }
            if requested_participant_ids:
                valid_participant_ids = set(
                    db.scalars(
                        select(Participant.id).where(
                            Participant.meeting_id == meeting_id,
                            Participant.id.in_(requested_participant_ids),
                        )
                    ).all()
                )
                if valid_participant_ids != requested_participant_ids:
                    raise _bad_request("participant_id must belong to this meeting")

            changed = False
            for mapping in request.mappings:
                speaker = speakers_by_label[mapping.speaker]
                if speaker.participant_id != mapping.participant_id:
                    speaker.participant_id = mapping.participant_id
                    changed = True

            if changed and meeting.confirmed_at is not None:
                meeting.confirmed_at = None

            response = SpeakerMappingsResponse(
                speakers=[
                    SpeakerMappingResponse(
                        label=speaker.label,
                        participant_id=speaker.participant_id,
                    )
                    for speaker in speakers
                ]
            )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("Could not update speakers for meeting %s", meeting_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update speakers",
        ) from exc

    return response


@router.post("/{meeting_id}/retry", response_model=MeetingCreateResponse)
def retry_meeting(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    user: Identity = Depends(current_user),
):
    with db.begin():
        meeting = db.scalar(
            select(Meeting)
            .where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
            .with_for_update()
        )
        if meeting is None:
            raise HTTPException(404, "Meeting not found")
        if (
            meeting.status != "failed"
            or meeting.confirmed_at
            or meeting.summary
            or meeting.segments
            or meeting.action_items
        ):
            raise HTTPException(
                409,
                "Повтор разрешён только для неудачной обработки без сохранённого результата",
            )
        if not meeting.audio_path or not Path(meeting.audio_path).is_file():
            raise HTTPException(
                409, "Запись отсутствует. Создайте новую встречу с аудио."
            )
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        active = db.scalar(
            select(func.count())
            .select_from(Meeting)
            .where(
                Meeting.owner_id == user.id, Meeting.status.in_(["queued", "running"])
            )
        )
        if active >= settings.max_active_meetings:
            raise HTTPException(429, "Дождитесь завершения текущих записей")
        job = db.scalar(
            select(Job)
            .where(Job.meeting_id == meeting.id)
            .order_by(Job.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if job is None:
            job = Job(meeting_id=meeting.id)
            db.add(job)
        job.status, job.attempts, job.run_after = "queued", 0, utc_now()
        job.claim_token = job.lease_until = job.error = job.finished_at = None
        meeting.status = meeting.processing_stage = "queued"
        meeting.error = None
    return MeetingCreateResponse(id=meeting.id, status=meeting.status)


@router.post("/{meeting_id}/reopen", response_model=MeetingCreateResponse)
def reopen_meeting(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    user: Identity = Depends(current_user),
):
    with db.begin():
        meeting = db.scalar(
            select(Meeting)
            .where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
            .with_for_update()
        )
        if meeting is None:
            raise HTTPException(404, "Meeting not found")
        if meeting.status != "completed":
            raise HTTPException(409, "Обработка ещё не завершена")
        meeting.confirmed_at = None
    return MeetingCreateResponse(id=meeting.id, status=meeting.status)


@router.post("/{meeting_id}/confirm", response_model=MeetingConfirmResponse)
def confirm_meeting(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    user: Identity = Depends(current_user),
) -> MeetingConfirmResponse:
    try:
        with db.begin():
            meeting = db.scalar(
                select(Meeting)
                .where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
                .with_for_update()
            )
            if meeting is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Meeting not found",
                )
            if meeting.status != "completed":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Only a completed meeting can be confirmed",
                )
            if meeting.confirmed_at is None:
                meeting.confirmed_at = utc_now()

            response = MeetingConfirmResponse(
                id=meeting.id,
                confirmed_at=meeting.confirmed_at.astimezone(timezone.utc),
            )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("Could not confirm meeting %s", meeting_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not confirm meeting",
        ) from exc

    return response


@router.get("/{meeting_id}/audio", response_class=FileResponse)
def get_meeting_audio(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    user: Identity = Depends(current_user),
) -> FileResponse:
    try:
        meeting = db.scalar(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
        )
        if meeting is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting not found",
            )
        audio_path_value = meeting.audio_path
        db.rollback()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Could not load audio for meeting %s", meeting_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load meeting audio",
        ) from exc

    if not audio_path_value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting audio not found",
        )

    audio_path = Path(audio_path_value).resolve()
    if (
        not audio_path.is_relative_to(Path(settings.storage_dir).resolve())
        or not audio_path.is_file()
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting audio not found",
        )

    extension = audio_path.suffix.casefold()
    return FileResponse(
        path=audio_path,
        media_type=AUDIO_MEDIA_TYPES.get(extension, "application/octet-stream"),
        filename=f"meeting-{meeting_id}{extension}",
        content_disposition_type="inline",
    )


@router.get("/{meeting_id}/export")
def export_meeting(
    meeting_id: UUID,
    export_format: str = Query(default="docx", alias="format"),
    db: Session = Depends(get_db),
    user: Identity = Depends(current_user),
) -> StreamingResponse:
    if export_format.casefold() != "docx":
        raise _bad_request("Only format=docx is supported")

    statement = (
        select(Meeting)
        .where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
        .options(
            selectinload(Meeting.participants),
            selectinload(Meeting.segments).joinedload(Segment.speaker),
            selectinload(Meeting.action_items),
        )
    )
    try:
        meeting = db.scalar(statement)
        if meeting is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting not found",
            )
        if meeting.status != "completed" or meeting.confirmed_at is None:
            raise HTTPException(409, "Сначала подтвердите завершённый протокол")
        export_data = _to_export_data(meeting)
        db.rollback()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Could not load meeting %s for export", meeting_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not export meeting",
        ) from exc

    document = build_meeting_docx(export_data)
    filename = f"meeting-{meeting_id}.docx"
    return StreamingResponse(
        document,
        media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
