import logging
import tempfile
import time
from pathlib import Path
from datetime import timedelta
from uuid import uuid4

import httpx

from fastapi import FastAPI, HTTPException, status, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, select, func
from sqlalchemy.exc import SQLAlchemyError

from .api.meetings import router as meetings_router
from .config import settings
from .db import engine
from .db import SessionLocal
from .auth import router as auth_router, current_user, Identity
from .models import WorkerHeartbeat, User
from alem_contract.asgi import BodyLimitMiddleware
from alem_contract.audio import MEDIA
from alem_contract.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="HackAlem API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(settings.frontend_origin).rstrip("/")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meetings_router)
app.include_router(auth_router)
app.add_middleware(
    BodyLimitMiddleware, max_bytes=settings.max_upload_mb * 1024 * 1024 + 1024 * 1024
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = str(uuid4())
    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith(("/meetings", "/auth")):
        response.headers["Cache-Control"] = "no-store"
    route = request.scope.get("route")
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "route": getattr(route, "path", "unknown"),
            "status": response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return response


@app.get("/capabilities")
def capabilities(user: Identity = Depends(current_user)):
    return {
        **MEDIA,
        "max_upload_mb": settings.max_upload_mb,
        "max_audio_seconds": settings.max_audio_seconds,
        "processing_profile": "backend_mock"
        if settings.ai_mode == "mock"
        else settings.ai_expected_mode,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            connection.execute(select(User.id).limit(1))
    except SQLAlchemyError as exc:
        logger.warning("database_not_ready type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable",
        ) from exc

    try:
        root = Path(settings.storage_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=root):
            pass
        with SessionLocal() as db:
            cutoff = db.scalar(select(func.now())) - timedelta(
                seconds=settings.worker_lease_seconds
            )
            if (
                db.scalar(
                    select(WorkerHeartbeat.id)
                    .where(WorkerHeartbeat.seen_at > cutoff)
                    .limit(1)
                )
                is None
            ):
                raise RuntimeError("worker")
        if settings.ai_mode != "mock":
            token = (
                settings.ai_internal_token.get_secret_value()
                if settings.ai_internal_token
                else ""
            )
            response = httpx.get(
                str(settings.ai_base_url).rstrip("/") + "/ready",
                headers={"X-Internal-Token": token},
                timeout=3,
                trust_env=False,
            )
            response.raise_for_status()
            state = response.json()
            if state.get("mode") != settings.ai_expected_mode:
                raise RuntimeError("ai_mode")
            if (
                state.get("max_audio_mb", 0) < settings.max_upload_mb
                or state.get("max_audio_seconds", 0) < settings.max_audio_seconds
            ):
                raise RuntimeError("ai_limits")
    except (OSError, RuntimeError, httpx.HTTPError, ValueError, SQLAlchemyError) as exc:
        logger.warning("processing_not_ready type=%s", type(exc).__name__)
        raise HTTPException(503, "Storage, worker or AI is not ready") from exc
    return {"status": "ready"}
