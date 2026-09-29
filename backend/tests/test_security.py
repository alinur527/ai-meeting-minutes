from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import worker
from app.config import settings
from app.main import app
from app.models import Meeting
from test_ai_integration import login_client, upload, wav_bytes  # noqa: F401


def test_owner_authorization_every_resource(database, monkeypatch):
    monkeypatch.setattr(settings, "ai_mode", "mock")
    owner = login_client(database)
    other = login_client(database, "other@example.test")
    meeting_id = upload(owner).json()["id"]
    assert worker.process_next_job()
    detail = owner.get(f"/meetings/{meeting_id}").json()
    task = detail["action_items"][0]["id"]
    routes = [
        ("GET", f"/meetings/{meeting_id}", None),
        ("GET", f"/meetings/{meeting_id}/audio", None),
        ("GET", f"/meetings/{meeting_id}/export", None),
        ("PATCH", f"/meetings/{meeting_id}/tasks/{task}", {"text": "attack"}),
        ("PATCH", f"/meetings/{meeting_id}/speakers", {"mappings": []}),
        ("POST", f"/meetings/{meeting_id}/confirm", None),
        ("POST", f"/meetings/{meeting_id}/reopen", None),
        ("POST", f"/meetings/{meeting_id}/retry", None),
    ]
    anonymous = TestClient(app)
    for method, route, payload in routes:
        assert anonymous.request(method, route, json=payload).status_code == 401
        assert other.request(method, route, json=payload).status_code == 404
    assert other.get("/meetings").json()["items"] == []
    assert (
        owner.get(f"/meetings/{meeting_id}").json()["action_items"][0]["text"]
        != "attack"
    )


def test_csrf_session_rotation_logout_and_legacy_isolation(database):
    client = login_client(database)
    meeting_id = upload(client).json()["id"]
    client.headers.pop("X-CSRF-Token")
    assert client.post(f"/meetings/{meeting_id}/confirm").status_code == 403
    assert (
        client.post(
            "/auth/login",
            headers={"Origin": "https://attacker.invalid"},
            json={"email": "owner@example.test", "password": "test-password-123"},
        ).status_code
        == 403
    )
    old = client.cookies.get("alem_session")
    login = client.post(
        "/auth/login",
        json={"email": "owner@example.test", "password": "test-password-123"},
    )
    assert login.status_code == 200 and client.cookies.get("alem_session") != old
    stale = TestClient(app)
    stale.cookies.set("alem_session", old)
    assert stale.get("/auth/session").status_code == 401
    with database.begin() as db:
        db.get(Meeting, UUID(meeting_id)).owner_id = None
    assert client.get(f"/meetings/{meeting_id}").status_code == 404
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/session").status_code == 401


@pytest.mark.parametrize(
    "filename,content,expected",
    [
        ("a.webm", b"audio", 415),
        ("a.ogg", b"audio", 415),
        ("a.mp4", b"audio", 415),
        ("a.wav", b"", 422),
        ("a.wav", b"RIFF0000WAVEbroken", 422),
        ("a.wav", b"x" * (1024 * 1024 + 1), 413),
    ],
    ids=["webm", "ogg", "mp4", "empty", "corrupt", "too-large"],
)
def test_bad_upload_leaves_no_job_or_file(
    database, monkeypatch, filename, content, expected
):
    from pathlib import Path

    monkeypatch.setattr(settings, "max_upload_mb", 1)
    monkeypatch.setattr(settings, "ai_mode", "mock")
    client = login_client(database)
    result = client.post(
        "/meetings",
        files={"file": (filename, content)},
        data={
            "title": "test",
            "started_at": "2026-09-25T10:00:00Z",
            "timezone": "UTC",
            "participants_json": '[{"name":"Test"}]',
        },
    )
    assert result.status_code == expected, result.text
    with database() as db:
        assert db.scalar(select(Meeting)) is None
    assert not list(Path(settings.storage_dir).glob("*"))


def test_login_rate_limit(database):
    client = TestClient(
        app, headers={"Origin": str(settings.frontend_origin).rstrip("/")}
    )
    for _ in range(10):
        assert (
            client.post(
                "/auth/login",
                json={"email": "absent@example.test", "password": "wrong"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/auth/login", json={"email": "absent@example.test", "password": "wrong"}
        ).status_code
        == 429
    )


def test_database_failure_does_not_leave_uploaded_file(database):
    from pathlib import Path
    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError

    client = login_client(database)

    def fail_meeting_flush(session, *_):
        if any(isinstance(row, Meeting) for row in session.new):
            raise SQLAlchemyError("simulated DB failure")

    event.listen(database.class_, "before_flush", fail_meeting_flush)
    try:
        assert upload(client).status_code == 500
    finally:
        event.remove(database.class_, "before_flush", fail_meeting_flush)
    with database() as db:
        assert db.scalar(select(Meeting)) is None
    assert not list(Path(settings.storage_dir).glob("*"))
