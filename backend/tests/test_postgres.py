import os
import subprocess
import sys
import time
import threading
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app import worker
from app.config import settings
from app.models import ActionItem, Job, Meeting, Segment, Speaker
from app.services.ai_processor import process_meeting
from app.services.remote_ai import AIServiceError
from test_ai_integration import login_client, upload  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Real PostgreSQL required; run scripts/run_postgres_tests.py",
)


def result_for(claim):
    return process_meeting(
        meeting_id=claim.meeting_id,
        audio_path=claim.audio_path,
        meeting_date=claim.meeting_date,
        timezone=claim.timezone,
        participants=claim.participants,
    )


def test_processing_date_is_local_meeting_date(database):
    client = login_client(database)
    meeting_id = upload(client).json()["id"]
    with database.begin() as db:
        meeting = db.get(Meeting, UUID(meeting_id))
        meeting.started_at = datetime(2026, 9, 25, 23, 30, tzinfo=timezone.utc)
        meeting.timezone = "Asia/Qyzylorda"
    assert worker.claim_next_job().meeting_date.isoformat() == "2026-09-26"


def test_two_workers_fencing_heartbeat_and_no_duplicates(database, monkeypatch):
    monkeypatch.setattr(settings, "ai_mode", "mock")
    client = login_client(database)
    meeting_id = upload(client).json()["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: worker.claim_next_job(), range(2)))
    assert sum(claim is not None for claim in claims) == 1
    first = next(claim for claim in claims if claim)
    assert worker.renew_lease(first)
    assert (
        worker.claim_next_job() is None
    )  # A long running, heartbeating owner remains owner.
    with database.begin() as db:
        db.get(Job, first.job_id).lease_until = db.scalar(
            select(func.now())
        ) - timedelta(seconds=1)
    second = worker.claim_next_job()
    assert second.attempt == 2 and second.claim_token != first.claim_token
    assert not worker.renew_lease(first)
    with pytest.raises(worker.WorkerStateError):
        worker.save_completed_result(first, result_for(first))
    worker.mark_failed(first, "stale failure")
    worker.save_completed_result(second, result_for(second))
    with pytest.raises(worker.WorkerStateError):
        worker.save_completed_result(second, result_for(second))
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Speaker)) == 2
        assert db.scalar(select(func.count()).select_from(Segment)) == 1
        assert db.scalar(select(func.count()).select_from(ActionItem)) == 1
        assert db.get(Meeting, UUID(meeting_id)).status == "completed"
    detail = client.get(f"/meetings/{meeting_id}").json()
    task_id = detail["action_items"][0]["id"]
    assert (
        client.patch(
            f"/meetings/{meeting_id}/tasks/{task_id}",
            json={"text": "Ручная правка", "reviewed": True},
        ).status_code
        == 200
    )
    assert client.post(f"/meetings/{meeting_id}/confirm").status_code == 200
    assert client.post(f"/meetings/{meeting_id}/retry").status_code == 409
    assert (
        client.get(f"/meetings/{meeting_id}").json()["action_items"][0]["text"]
        == "Ручная правка"
    )
    # A duplicate legacy job may own another valid token. Its failure must not
    # demote a saved/confirmed meeting or hide the user's protocol.
    duplicate_id, duplicate_token = uuid4(), uuid4()
    with database.begin() as db:
        db.add(
            Job(
                id=duplicate_id,
                meeting_id=UUID(meeting_id),
                status="running",
                attempts=1,
                claim_token=duplicate_token,
                lease_until=db.scalar(select(func.now())) + timedelta(minutes=5),
            )
        )
    worker.mark_failed(
        replace(second, job_id=duplicate_id, claim_token=duplicate_token),
        "duplicate failure",
        retryable=True,
    )
    persisted = client.get(f"/meetings/{meeting_id}").json()
    assert persisted["status"] == "completed" and persisted["confirmed_at"]
    assert persisted["action_items"][0]["text"] == "Ручная правка"


def test_abrupt_worker_exit_recovers_after_lease(database, monkeypatch):
    monkeypatch.setattr(settings, "ai_mode", "mock")
    client = login_client(database)
    meeting_id = upload(client).json()["id"]
    code = "from app import worker; import os; worker.settings.worker_lease_seconds=1; assert worker.claim_next_job(); os._exit(9)"
    crashed = subprocess.run([sys.executable, "-c", code], timeout=15)
    assert crashed.returncode == 9
    time.sleep(1.2)
    assert worker.process_next_job()
    assert client.get(f"/meetings/{meeting_id}").json()["status"] == "completed"
    with database() as db:
        assert db.scalar(select(Job)).attempts == 2


def test_heartbeat_retains_a_long_job(database, monkeypatch):
    monkeypatch.setattr(settings, "worker_lease_seconds", 1)
    monkeypatch.setattr(settings, "worker_heartbeat_seconds", 0.15)
    upload(login_client(database))
    claim = worker.claim_next_job()
    done = threading.Event()
    thread = threading.Thread(target=worker.heartbeat, args=(claim, done))
    thread.start()
    try:
        time.sleep(
            1.3
        )  # Longer than the original lease, while the owner remains alive.
        assert worker.claim_next_job() is None
    finally:
        done.set()
        thread.join(5)
    assert not thread.is_alive()


def test_transient_backoff_permanent_failure_and_manual_retry(database, monkeypatch):
    monkeypatch.setattr(settings, "ai_mode", "mock")
    client = login_client(database)
    meeting_id = upload(client).json()["id"]
    actual = worker.process_meeting

    def unavailable(**_):
        raise AIServiceError("Temporary AI outage", retryable=True)

    monkeypatch.setattr(worker, "process_meeting", unavailable)
    assert worker.process_next_job()
    assert not worker.process_next_job()
    with database.begin() as db:
        job = db.scalar(select(Job))
        assert job.status == "queued" and job.attempts == 1
        job.run_after = db.scalar(select(func.now())) - timedelta(seconds=1)

    def permanent(**_):
        raise AIServiceError("Invalid model response")

    monkeypatch.setattr(worker, "process_meeting", permanent)
    assert worker.process_next_job()
    assert client.get(f"/meetings/{meeting_id}").json()["status"] == "failed"
    assert client.post(f"/meetings/{meeting_id}/retry").status_code == 200
    assert client.post(f"/meetings/{meeting_id}/retry").status_code == 409
    monkeypatch.setattr(worker, "process_meeting", actual)
    assert worker.process_next_job()
    assert client.get(f"/meetings/{meeting_id}").json()["status"] == "completed"
