from __future__ import annotations

import io
import json
import wave
from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 16_000)
    return output.getvalue()


def meta_payload() -> dict:
    return {
        "meeting_id": "mtg_20260923_1400",
        "meeting_date": "2026-09-23",
        "timezone": "Asia/Almaty",
        "participants": [
            {"id": "p1", "name": "Даурен Ахметов"},
            {"id": "p2", "name": "Айгерим Сериковна"},
        ],
    }


def client() -> TestClient:
    settings = replace(Settings.from_env(), mode="mock", internal_token="unit-test-token")
    return TestClient(create_app(settings), headers={"X-Internal-Token": "unit-test-token"})


def test_mock_process_contract() -> None:
    response = client().post(
        "/internal/process",
        files={
            "audio": ("meeting.wav", wav_bytes(), "audio/wav"),
            "meta": (None, json.dumps(meta_payload(), ensure_ascii=False)),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meeting_id"] == "mtg_20260923_1400"
    assert body["status"] == "ok"
    assert body["language_detected"] == "mixed-ru-kk"
    assert body["segments"][0]["speaker"] == "SPEAKER_00"
    assert body["action_items"][0]["due_date"] == "2026-09-25"
    assert set(body["processing_meta"]) == {
        "mode",
        "asr_model",
        "diarization_model",
        "processed_at",
        "model_version",
    }


def test_invalid_meta_has_clear_422() -> None:
    response = client().post(
        "/internal/process",
        files={
            "audio": ("meeting.wav", wav_bytes(), "audio/wav"),
            "meta": (None, "{broken"),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_META"


def test_corrupted_audio_has_clear_422() -> None:
    response = client().post(
        "/internal/process",
        files={
            "audio": ("meeting.wav", b"not a wave", "audio/wav"),
            "meta": (None, json.dumps(meta_payload())),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CORRUPTED_AUDIO"


def test_export_docx_and_pdf() -> None:
    process_response = (
        client()
        .post(
            "/internal/process",
            files={
                "audio": ("meeting.wav", wav_bytes(), "audio/wav"),
                "meta": (None, json.dumps(meta_payload())),
            },
        )
        .json()
    )
    docx = client().post("/internal/export/docx", json=process_response)
    pdf = client().post("/internal/export/pdf", json=process_response)
    assert docx.status_code == 200
    assert docx.content.startswith(b"PK")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
