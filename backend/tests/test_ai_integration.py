import copy
import io
import json
import wave
from datetime import date
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app import worker
from app.config import settings
from app.auth import password_hasher
from app.main import app
from app.models import Job, Meeting, User
from app.services import remote_ai
from app.services.ai_processor import (
    ProcessingParticipant,
    process_meeting,
    validate_result,
)
from app.services.remote_ai import AIServiceError, adapt_response


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000)
    return output.getvalue()


@pytest.mark.parametrize(
    ("code", "status", "expected", "retryable"),
    [
        ("TRANSCRIPT_TOO_LONG", 422, "Разделите запись", False),
        ("RESOURCE_LIMIT", 503, "не хватает памяти", True),
        ("UNKNOWN_PRIVATE_CODE", 422, "ИИ отклонил аудио", False),
    ],
)
def test_ai_error_envelope_is_safe_and_actionable(
    tmp_path, monkeypatch, code, status, expected, retryable
):
    audio = tmp_path / "speech.wav"
    audio.write_bytes(wav_bytes())
    original_client = httpx.Client
    monkeypatch.setattr(
        remote_ai.httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    status,
                    json={"error": {"code": code, "message": "private-server-detail"}},
                )
            ),
            **kwargs,
        ),
    )
    with pytest.raises(AIServiceError) as caught:
        remote_ai.request_processing(audio_path=str(audio), meta={})
    assert expected in str(caught.value)
    assert "private-server-detail" not in str(caught.value)
    assert caught.value.retryable is retryable


def login_client(factory, email="owner@example.test"):
    with factory.begin() as db:
        if not db.scalar(select(User.id).where(User.email == email)):
            db.add(
                User(
                    email=email,
                    name="Test user",
                    password_hash=password_hasher.hash("test-password-123"),
                )
            )
    client = TestClient(
        app, headers={"Origin": str(settings.frontend_origin).rstrip("/")}
    )
    response = client.post(
        "/auth/login", json={"email": email, "password": "test-password-123"}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


def upload(client, filename="meeting.wav"):
    return client.post(
        "/meetings",
        files={"file": (filename, wav_bytes(), "audio/wav")},
        data={
            "title": "Интеграция",
            "started_at": "2026-09-23T10:00:00+00:00",
            "timezone": "Asia/Almaty",
            "participants_json": json.dumps([{"name": "Султан"}, {"name": "Даурен"}]),
        },
    )


def test_api_worker_live_ai_and_export(database, ai_url, monkeypatch):
    monkeypatch.setattr(settings, "ai_base_url", ai_url)
    monkeypatch.setattr(
        settings, "ai_internal_token", SecretStr("integration-test-token")
    )
    with login_client(database) as client:
        created = upload(client)
        assert created.status_code == 202, created.text
        meeting_id = created.json()["id"]
        assert worker.process_next_job()
        detail = client.get(f"/meetings/{meeting_id}").json()
        assert detail["status"] == "completed", detail
        assert len(detail["segments"]) == 2
        task = detail["action_items"][0]
        assignee_name = next(
            participant["name"]
            for participant in detail["participants"]
            if participant["id"] == task["assignee_id"]
        )
        assert assignee_name in detail["segments"][0]["text"]
        assert task["assignee_id"] == detail["participants"][0]["id"]
        assert task["due_date"] == "2026-09-25"
        assert set(task["source_segment_ids"]) == {s["id"] for s in detail["segments"]}
        assert (
            client.get(f"/meetings/{meeting_id}/export?format=docx").status_code == 409
        )
        assert client.post(f"/meetings/{meeting_id}/confirm").status_code == 200
        document = client.get(f"/meetings/{meeting_id}/export?format=docx")
        assert document.status_code == 200
        assert document.content.startswith(b"PK")
    with database() as session:
        job = session.scalar(select(Job))
        assert job.status == "completed" and job.attempts == 1
        assert job.finished_at is not None
    assert worker.process_next_job() is False


def test_wrong_token_marks_job_failed(database, ai_url, monkeypatch):
    monkeypatch.setattr(settings, "ai_base_url", ai_url)
    monkeypatch.setattr(settings, "ai_internal_token", SecretStr("wrong-token"))
    with login_client(database) as client:
        meeting_id = upload(client).json()["id"]
        assert worker.process_next_job()
        detail = client.get(f"/meetings/{meeting_id}").json()
        assert detail["status"] == "failed"
        assert "AI_INTERNAL_TOKEN" in detail["error"]
        assert detail["segments"] == []
    with database() as session:
        assert session.scalar(select(Job)).status == "failed"


def test_unsupported_format_rejected_before_queue(database):
    with login_client(database) as client:
        assert upload(client, "meeting.webm").status_code == 415
    with database() as session:
        assert session.scalar(select(Meeting)) is None


@pytest.fixture
def payload():
    return {
        "meeting_id": str(uuid4()),
        "status": "ok",
        "summary": "Решили",
        "language_detected": "ru",
        "duration_ms": 1000,
        "processing_meta": {
            "mode": "mock",
            "asr_model": "mock",
            "diarization_model": "mock",
            "processed_at": "2026-09-25T10:00:00Z",
            "model_version": "test",
        },
        "speakers": {"SPEAKER_00": {"participant_id": str(uuid4())}},
        "segments": [
            {
                "id": 7,
                "speaker": "SPEAKER_00",
                "start_ms": 0,
                "end_ms": 900,
                "text": "Сделать",
            }
        ],
        "action_items": [
            {
                "id": 0,
                "text": "Сделать",
                "assignee_speaker_label": "SPEAKER_00",
                "due_text_raw": "позже",
                "evidence_segment_ids": [7],
            }
        ],
    }


def test_adapter_preserves_evidence_and_flags_unresolved_deadline(payload):
    result = adapt_response(payload, meeting_id=payload["meeting_id"])
    participant = UUID(payload["speakers"]["SPEAKER_00"]["participant_id"])
    parsed = validate_result(result, participant_ids=[participant])
    task = parsed.action_items[0]
    assert task.assignee_id == participant
    assert task.source_segment_indexes == [7]
    assert task.deadline_text == "позже"
    assert task.needs_review and "Срок" in task.review_reason


@pytest.mark.parametrize(
    "fault",
    [
        "foreign_participant",
        "bad_evidence",
        "duplicate_segment",
        "unknown_speaker",
        "negative_duration",
        "wrong_meeting",
        "error_status",
    ],
)
def test_untrusted_responses_rejected(payload, fault):
    participant = UUID(payload["speakers"]["SPEAKER_00"]["participant_id"])
    meeting_id = payload["meeting_id"]
    if fault == "foreign_participant":
        payload["action_items"][0]["assignee_participant_id"] = str(uuid4())
    elif fault == "bad_evidence":
        payload["action_items"][0]["evidence_segment_ids"] = [999]
    elif fault == "duplicate_segment":
        payload["segments"].append(copy.deepcopy(payload["segments"][0]))
    elif fault == "unknown_speaker":
        payload["segments"][0]["speaker"] = "SPEAKER_99"
    elif fault == "negative_duration":
        payload["segments"][0].update(start_ms=1000, end_ms=500)
    elif fault == "wrong_meeting":
        payload["meeting_id"] = str(uuid4())
    elif fault == "error_status":
        payload["status"] = "error"
    with pytest.raises((AIServiceError, ValidationError)):
        validate_result(
            adapt_response(payload, meeting_id=meeting_id),
            participant_ids=[participant],
        )


@pytest.mark.parametrize("failure", ["timeout", "connection", "not_json"])
def test_transport_failures_are_actionable(tmp_path, monkeypatch, failure):
    path = tmp_path / "test.wav"
    path.write_bytes(wav_bytes())
    original_client = httpx.Client

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("test", request=request)
        if failure == "connection":
            raise httpx.ConnectError("test", request=request)
        return httpx.Response(200, text="not JSON")

    monkeypatch.setattr(
        remote_ai.httpx,
        "Client",
        lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(AIServiceError):
        remote_ai.request_processing(
            audio_path=str(path), meta={"meeting_id": str(uuid4())}
        )


def test_local_mock_still_works(monkeypatch):
    monkeypatch.setattr(settings, "ai_mode", "mock")
    result = process_meeting(
        meeting_id=uuid4(),
        audio_path=None,
        meeting_date=date(2026, 9, 23),
        timezone="Asia/Almaty",
        participants=[ProcessingParticipant(id=uuid4(), name="Султан")],
    )
    assert result.segments


def test_mock_response_cannot_pass_as_real(payload, monkeypatch):
    monkeypatch.setattr(settings, "ai_expected_mode", "real")
    with pytest.raises(AIServiceError, match="AI_EXPECTED_MODE"):
        adapt_response(payload, meeting_id=payload["meeting_id"])


def test_oversized_ai_response_stops_reading(tmp_path, monkeypatch):
    reads = []

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(20):
                reads.append(1)
                yield b"x" * 65536

    path = tmp_path / "audio.wav"
    path.write_bytes(wav_bytes())
    original = httpx.Client
    monkeypatch.setattr(remote_ai, "MAX_RESPONSE_BYTES", 2 * 65536)
    monkeypatch.setattr(
        remote_ai.httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=Stream())
            ),
            **kw,
        ),
    )
    with pytest.raises(AIServiceError):
        remote_ai.request_processing(
            audio_path=str(path), meta={"meeting_id": str(uuid4())}
        )
    assert len(reads) == 3
