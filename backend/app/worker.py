import argparse
import logging
import threading
import signal
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from alem_contract.logging import configure_logging

from sqlalchemy import select, or_, and_, update, func
from sqlalchemy.orm import Session

from .db import SessionLocal
from .config import settings
from .models import (
    ActionItem,
    Job,
    Meeting,
    Participant,
    Segment,
    Speaker,
    WorkerHeartbeat,
)
from .models.base import utc_now
from .services.ai_processor import (
    MeetingProcessingResult,
    ProcessingParticipant,
    process_meeting,
)
from .services.remote_ai import AIServiceError

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
MAX_ERROR_LENGTH = 255
WORKER_ID = uuid4()
STOP = threading.Event()


@dataclass(frozen=True)
class ClaimedJob:
    job_id: UUID
    claim_token: UUID
    attempt: int
    meeting_id: UUID
    audio_path: str | None
    meeting_date: date
    timezone: str
    participants: tuple[ProcessingParticipant, ...]


class WorkerStateError(RuntimeError):
    """Raised when a claimed job can no longer be completed safely."""


def pulse_worker() -> None:
    with SessionLocal.begin() as session:
        row = session.get(WorkerHeartbeat, WORKER_ID)
        now = session.scalar(select(func.now()))
        if row is None:
            session.add(WorkerHeartbeat(id=WORKER_ID, seen_at=now))
        else:
            row.seen_at = now


def claim_next_job() -> ClaimedJob | None:
    """Claim queued or expired work under a PostgreSQL row lock and a fresh fence."""
    with SessionLocal.begin() as session:
        now = session.scalar(select(func.now()))
        job = session.scalar(
            select(Job)
            .where(
                or_(
                    and_(Job.status == "queued", Job.run_after <= now),
                    and_(Job.status == "running", Job.lease_until <= now),
                )
            )
            .order_by(Job.run_after, Job.created_at, Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        meeting = session.get(Meeting, job.meeting_id, with_for_update=True)
        if meeting is None or meeting.status not in {"queued", "running"}:
            job.status, job.error = (
                "failed",
                "Meeting cannot be processed in its current state",
            )
            return None
        if job.attempts >= settings.job_max_attempts:
            job.status = meeting.status = meeting.processing_stage = "failed"
            job.error = meeting.error = (
                "Попытки обработки исчерпаны после остановки worker. Можно повторить."
            )
            job.finished_at = now
            return None
        participants = tuple(
            ProcessingParticipant(id=p.id, name=p.name)
            for p in session.scalars(
                select(Participant)
                .where(Participant.meeting_id == meeting.id)
                .order_by(Participant.created_at, Participant.id)
            )
        )
        token = uuid4()
        job.status, job.claim_token = "running", token
        job.attempts += 1
        job.started_at, job.lease_until = (
            now,
            now + timedelta(seconds=settings.worker_lease_seconds),
        )
        job.finished_at = job.error = None
        meeting.status, meeting.processing_stage, meeting.error = "running", "ai", None
        claimed = ClaimedJob(
            job_id=job.id,
            claim_token=token,
            attempt=job.attempts,
            meeting_id=meeting.id,
            audio_path=meeting.audio_path,
            meeting_date=meeting.started_at.astimezone(
                ZoneInfo(meeting.timezone)
            ).date(),
            timezone=meeting.timezone,
            participants=participants,
        )
    logger.info(
        "job_claimed",
        extra={
            "job_id": claimed.job_id,
            "meeting_id": claimed.meeting_id,
            "attempt": claimed.attempt,
        },
    )
    return claimed


def renew_lease(claimed: ClaimedJob) -> bool:
    with SessionLocal.begin() as session:
        now = session.scalar(select(func.now()))
        result = session.execute(
            update(Job)
            .where(
                Job.id == claimed.job_id,
                Job.status == "running",
                Job.claim_token == claimed.claim_token,
                Job.lease_until > now,
            )
            .values(lease_until=now + timedelta(seconds=settings.worker_lease_seconds))
        )
        return result.rowcount == 1


def heartbeat(claimed: ClaimedJob, done: threading.Event) -> None:
    while not done.wait(settings.worker_heartbeat_seconds):
        try:
            pulse_worker()
            if not renew_lease(claimed):
                return
        except Exception as exc:
            logger.warning(
                "heartbeat_failed job=%s type=%s", claimed.job_id, type(exc).__name__
            )


def _load_running_job(session: Session, claimed_job: ClaimedJob) -> Job:
    statement = (
        select(Job)
        .where(
            Job.id == claimed_job.job_id,
            Job.status == "running",
            Job.claim_token == claimed_job.claim_token,
            Job.lease_until > func.now(),
        )
        .with_for_update()
    )
    job = session.scalar(statement)
    if job is None or job.meeting_id != claimed_job.meeting_id:
        raise WorkerStateError("Job is no longer in the claimed running state")
    return job


def save_completed_result(
    claimed_job: ClaimedJob,
    result: MeetingProcessingResult,
) -> None:
    """Persist the complete processor result and final statuses atomically."""

    with SessionLocal() as session:
        with session.begin():
            job = _load_running_job(session, claimed_job)
            meeting = session.get(Meeting, claimed_job.meeting_id, with_for_update=True)
            if meeting is None or meeting.status != "running":
                raise WorkerStateError("Meeting is no longer in the running state")

            if (
                meeting.confirmed_at
                or meeting.summary is not None
                or meeting.segments
                or meeting.action_items
            ):
                raise WorkerStateError("Refusing to overwrite a saved protocol")
            speakers_by_label: dict[str, Speaker] = {}
            for speaker_result in result.speakers:
                speaker = Speaker(
                    meeting_id=meeting.id,
                    label=speaker_result.label,
                    participant_id=speaker_result.participant_id,
                )
                session.add(speaker)
                speakers_by_label[speaker_result.label] = speaker
            session.flush()

            segments_by_index: dict[int, Segment] = {}
            for segment_result in result.segments:
                segment = Segment(
                    meeting_id=meeting.id,
                    speaker_id=speakers_by_label[segment_result.speaker_label].id,
                    segment_index=segment_result.segment_index,
                    start_ms=segment_result.start_ms,
                    end_ms=segment_result.end_ms,
                    text=segment_result.text,
                )
                session.add(segment)
                segments_by_index[segment_result.segment_index] = segment
            session.flush()

            for action_item_result in result.action_items:
                action_item = ActionItem(
                    meeting_id=meeting.id,
                    text=action_item_result.text,
                    assignee_id=action_item_result.assignee_id,
                    due_date=action_item_result.due_date,
                    deadline_text=action_item_result.deadline_text,
                    needs_review=action_item_result.needs_review,
                    review_reason=action_item_result.review_reason,
                    source_segments=[
                        segments_by_index[index]
                        for index in action_item_result.source_segment_indexes
                    ],
                )
                session.add(action_item)

            now = utc_now()
            meeting.summary = result.summary
            meeting.processing_mode = result.processing_mode
            meeting.processing_stage = "completed"
            meeting.status = "completed"
            meeting.error = None

            job.status = "completed"
            job.finished_at = now
            job.error = None
            job.claim_token = job.lease_until = None


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, AIServiceError):
        return str(exc)[:MAX_ERROR_LENGTH]
    message = f"Worker processing failed ({type(exc).__name__})"
    return message[:MAX_ERROR_LENGTH]


def mark_failed(
    claimed_job: ClaimedJob, error: str, *, retryable: bool = False
) -> None:
    with SessionLocal.begin() as session:
        try:
            job = _load_running_job(session, claimed_job)
        except WorkerStateError:
            return  # An expired attempt cannot alter the new owner's state.
        meeting = session.get(Meeting, claimed_job.meeting_id, with_for_update=True)
        now = session.scalar(select(func.now()))
        protected = meeting is not None and (
            meeting.status == "completed" or meeting.confirmed_at is not None
        )
        retry = retryable and job.attempts < settings.job_max_attempts and not protected
        job.status = "queued" if retry else "failed"
        job.error = error
        job.claim_token = job.lease_until = None
        job.finished_at = None if retry else now
        job.run_after = now + timedelta(
            seconds=min(300, settings.retry_base_seconds * 2 ** (job.attempts - 1))
        )
        if meeting is not None and not protected:
            meeting.status = job.status
            meeting.processing_stage = "waiting_retry" if retry else "failed"
            meeting.error = error


def process_next_job() -> bool:
    claimed = claim_next_job()
    if claimed is None:
        return False
    done = threading.Event()
    thread = threading.Thread(target=heartbeat, args=(claimed, done), daemon=True)
    thread.start()
    try:
        path = Path(claimed.audio_path).resolve() if claimed.audio_path else None
        if (
            path is None
            or not path.is_relative_to(Path(settings.storage_dir).resolve())
            or not path.is_file()
        ):
            raise AIServiceError(
                "Аудиофайл отсутствует в хранилище worker. Восстановите файл из резервной копии."
            )
        result = process_meeting(
            meeting_id=claimed.meeting_id,
            audio_path=claimed.audio_path,
            meeting_date=claimed.meeting_date,
            timezone=claimed.timezone,
            participants=claimed.participants,
        )
        save_completed_result(claimed, result)
        logger.info(
            "job_completed",
            extra={
                "job_id": claimed.job_id,
                "meeting_id": claimed.meeting_id,
                "attempt": claimed.attempt,
            },
        )
    except Exception as exc:
        logger.error(
            "job_failed",
            extra={
                "job_id": claimed.job_id,
                "meeting_id": claimed.meeting_id,
                "attempt": claimed.attempt,
                "error_type": type(exc).__name__,
            },
        )
        try:
            mark_failed(
                claimed,
                _safe_error(exc),
                retryable=isinstance(exc, AIServiceError) and exc.retryable,
            )
        except Exception as failure:
            logger.error(
                "failure_persist_failed job=%s type=%s",
                claimed.job_id,
                type(failure).__name__,
            )
    finally:
        done.set()
        thread.join(timeout=5)
    return True


def run_worker(*, once: bool = False) -> None:
    logger.info("worker_started worker=%s", WORKER_ID)
    while not STOP.is_set():
        try:
            pulse_worker()
            processed = process_next_job()
        except Exception as exc:
            logger.error("worker_iteration_failed type=%s", type(exc).__name__)
            processed = False
        if once:
            return
        if not processed:
            STOP.wait(POLL_INTERVAL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued HackAlem meetings")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one polling iteration and exit",
    )
    args = parser.parse_args()
    configure_logging()
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    run_worker(once=args.once)


if __name__ == "__main__":
    main()
