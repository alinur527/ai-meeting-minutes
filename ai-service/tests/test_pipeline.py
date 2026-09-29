from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from app.config import Settings
from app.errors import ServiceError
from app.pipeline.asr import ASRResult, ASRSegment
from app.pipeline.diarization import SpeakerTurn
from app.pipeline.llm import OllamaExtractor
from app.pipeline.service import MeetingPipeline
from app.schemas import ExtractedActionItem, LLMExtraction, MeetingMeta


class FakeASR:
    def transcribe(self, _: Path) -> ASRResult:
        return ASRResult(
            segments=[ASRSegment(0, 2000, "Меня зовут Даурен Ахметов. Сделаю отчет к пятнице.")],
            language="ru",
            duration_ms=2000,
        )


class FakeDiarizer:
    def diarize(self, _: Path) -> list[SpeakerTurn]:
        return [SpeakerTurn(0, 2000, "SPEAKER_00")]


class FakeExtractor:
    def extract(self, segments, meta) -> LLMExtraction:
        return LLMExtraction(
            summary="Нужно подготовить отчет.",
            action_items=[
                ExtractedActionItem(
                    text="Подготовить отчет",
                    assignee_speaker_label="SPEAKER_00",
                    due_text_raw="к пятнице",
                    evidence_segment_ids=[0],
                )
            ],
        )


def test_real_pipeline_orchestration_with_local_stage_fakes() -> None:
    pipeline = MeetingPipeline(replace(Settings.from_env(), mode="real"))
    pipeline.asr = FakeASR()
    pipeline.diarizer = FakeDiarizer()
    pipeline.extractor = FakeExtractor()
    meta = MeetingMeta(
        meeting_id="m1",
        meeting_date=date(2026, 9, 23),
        timezone="Asia/Almaty",
        participants=[{"id": "p1", "name": "Даурен Ахметов"}],
    )

    result = pipeline.process(Path("unused.wav"), meta)

    assert result.speakers["SPEAKER_00"].participant_id == "p1"
    assert result.action_items[0].assignee_participant_id == "p1"
    assert result.action_items[0].due_date == date(2026, 9, 25)


@pytest.mark.parametrize("introduced", [False, True])
def test_named_assignee_does_not_inherit_the_ordering_voice(introduced):
    pipeline = MeetingPipeline(replace(Settings.from_env(), mode="real"))
    pipeline.asr = FakeASR()
    pipeline.diarizer = FakeDiarizer()
    pipeline.extractor = FakeExtractor()
    if not introduced:
        pipeline.asr.transcribe = lambda _: ASRResult(
            [ASRSegment(0, 2000, "Айгуль, подготовь отчёт.")], "ru", 2000
        )
    extraction = FakeExtractor().extract([], None)
    extraction.action_items[0].assignee_participant_id = "p2"
    pipeline.extractor.extract = lambda segments, meta: extraction
    meta = MeetingMeta(
        meeting_id="named-owner",
        meeting_date="2026-09-25",
        timezone="UTC",
        participants=[{"id": "p1", "name": "Даурен Ахметов"}, {"id": "p2", "name": "Айгуль"}],
    )
    result = pipeline.process(Path("unused.wav"), meta)
    assert result.action_items[0].assignee_participant_id == "p2"
    assert result.action_items[0].assignee_speaker_label is None


def test_ollama_startup_check_reports_missing_model(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"models": [{"name": "another-model:latest"}]}

    monkeypatch.setattr("app.pipeline.llm.httpx.get", lambda *args, **kwargs: FakeResponse())
    extractor = OllamaExtractor(replace(Settings.from_env(), llm_model="required:model"))

    try:
        extractor.ensure_model_available()
    except ServiceError as exc:
        assert exc.code == "LLM_MODEL_UNAVAILABLE"
        assert "required:model" in exc.message
        assert "another-model:latest" in exc.message
    else:
        raise AssertionError("missing Ollama model must fail the startup check")
