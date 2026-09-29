from __future__ import annotations

import json
import logging
import secrets
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from alem_contract.asgi import BodyLimitMiddleware
from alem_contract.audio import AudioValidationError, inspect_audio
from alem_contract.logging import configure_logging
from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.audio import validate_audio
from app.config import Settings
from app.errors import ServiceError
from app.exporters import export_docx, export_pdf
from app.pipeline.service import MeetingPipeline
from app.schemas import MeetingMeta, ProcessResponse

configure_logging()
logger = logging.getLogger("ai_service")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    pipeline = MeetingPipeline(resolved_settings)
    processing_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if not resolved_settings.internal_token:
            raise RuntimeError("INTERNAL_TOKEN is required")
        if resolved_settings.mode == "real":
            try:
                await run_in_threadpool(pipeline.extractor.ensure_model_available)
                logger.info(
                    "startup_check_completed component=ollama model=%s", resolved_settings.llm_model
                )
                await run_in_threadpool(pipeline.asr._load)
                logger.info(
                    "startup_check_completed component=asr model=%s", resolved_settings.asr_model
                )
                if resolved_settings.low_memory_mode:
                    pipeline.asr.unload()
                await run_in_threadpool(pipeline.diarizer._load)
                logger.info(
                    "startup_check_completed component=diarization model=%s",
                    resolved_settings.diarization_model,
                )
                if resolved_settings.low_memory_mode:
                    pipeline.diarizer.unload()
            except ServiceError as exc:
                logger.critical("startup_check_failed code=%s message=%s", exc.code, exc.message)
                raise
        app.state.ready = True
        yield
        app.state.ready = False

    app = FastAPI(
        title="Hackalem Meeting AI Service",
        version="0.1.0",
        description="Offline ASR, speaker diarization and meeting action-item extraction.",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.pipeline = pipeline
    app.state.ready = False
    app.add_middleware(
        BodyLimitMiddleware, max_bytes=resolved_settings.max_audio_mb * 1024 * 1024 + 1024 * 1024
    )

    @app.exception_handler(ServiceError)
    async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
        logger.warning("service_error code=%s", exc.code)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "context": exc.context}},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "location": list(error.get("loc", ())),
                "message": error.get("msg", "invalid value"),
                "type": error.get("type", "validation_error"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "request validation failed",
                    "context": {"errors": errors},
                }
            },
        )

    def authorize(
        x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
    ) -> None:
        expected = resolved_settings.internal_token
        if not expected:
            raise ServiceError("NOT_CONFIGURED", "INTERNAL_TOKEN is required", status_code=503)
        if not secrets.compare_digest(x_internal_token or "", expected):
            raise ServiceError("UNAUTHORIZED", "invalid internal service token", status_code=401)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": resolved_settings.mode}

    @app.get("/ready", dependencies=[Depends(authorize)])
    async def ready():
        if not app.state.ready:
            raise ServiceError("NOT_READY", "Models are not ready", status_code=503)
        if resolved_settings.mode == "real":
            await run_in_threadpool(pipeline.extractor.ensure_model_available)
        return {
            "status": "ready",
            "mode": resolved_settings.mode,
            "max_audio_mb": resolved_settings.max_audio_mb,
            "max_audio_seconds": resolved_settings.max_audio_seconds,
        }

    @app.post(
        "/internal/process",
        response_model=ProcessResponse,
        dependencies=[Depends(authorize)],
    )
    async def process_meeting(
        audio: Annotated[UploadFile, File(description="WAV, MP3 or M4A meeting audio")],
        meta: Annotated[str, Form(description="MeetingMeta JSON string")],
    ) -> ProcessResponse:
        parsed_meta = _parse_meta(meta)
        max_bytes = resolved_settings.max_audio_mb * 1024 * 1024
        if not processing_lock.acquire(blocking=False):
            raise ServiceError("BUSY", "AI занят другой записью. Повторите позже.", status_code=503)
        try:
            first = await audio.read(1024 * 1024)
            suffix = validate_audio(audio.filename, first, max_bytes)
            with tempfile.TemporaryDirectory(prefix="meeting-ai-") as temporary_directory:
                audio_path = Path(temporary_directory) / f"input{suffix}"
                total = len(first)
                with audio_path.open("wb") as output:
                    output.write(first)
                    while chunk := await audio.read(1024 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise ServiceError(
                                "AUDIO_TOO_LARGE", "Audio is too large", status_code=413
                            )
                        output.write(chunk)
                await run_in_threadpool(
                    inspect_audio,
                    audio_path,
                    max_bytes=max_bytes,
                    max_seconds=resolved_settings.max_audio_seconds,
                )
                result = await run_in_threadpool(pipeline.process, audio_path, parsed_meta)
                result.validate_participants({person.id for person in parsed_meta.participants})
                return result
        except AudioValidationError as exc:
            raise ServiceError("CORRUPTED_AUDIO", str(exc), status_code=422) from exc
        except MemoryError as exc:
            raise ServiceError(
                "RESOURCE_LIMIT",
                "Недостаточно памяти. Уменьшите запись или модель.",
                status_code=422,
            ) from exc
        except ValueError as exc:
            raise ServiceError(
                "INVALID_AI_RESULT", "Результат AI не прошёл проверку", status_code=422
            ) from exc
        finally:
            await audio.close()
            processing_lock.release()

    @app.post(
        "/internal/export/{document_format}",
        dependencies=[Depends(authorize)],
        responses={
            200: {
                "content": {
                    "application/pdf": {},
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
                }
            }
        },
    )
    async def export_protocol(
        document_format: Literal["pdf", "docx"], protocol: ProcessResponse
    ) -> Response:
        if document_format == "pdf":
            content = await run_in_threadpool(export_pdf, protocol)
            media_type = "application/pdf"
        else:
            content = await run_in_threadpool(export_docx, protocol)
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = quote(f"protocol-{protocol.meeting_id}.{document_format}")
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )

    return app


def _parse_meta(raw: str) -> MeetingMeta:
    try:
        return MeetingMeta.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as exc:
        if isinstance(exc, ValidationError):
            details = [
                {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
                for item in exc.errors()
            ]
        else:
            details = [{"message": str(exc)}]
        raise ServiceError(
            "INVALID_META",
            "meta must be valid JSON matching the MeetingMeta schema",
            status_code=422,
            context={"errors": details},
        ) from exc


app = create_app()
