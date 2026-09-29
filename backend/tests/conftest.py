import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
defaults = dict(
    APP_ENV="test",
    COOKIE_SECURE="false",
    AI_EXPECTED_MODE="mock",
    DATABASE_URL="sqlite://",
    STORAGE_DIR="test-storage",
    AI_BASE_URL="http://127.0.0.1:8000",
    AI_MODE="http",
    FRONTEND_ORIGIN="http://localhost:5173",
)
for key, value in defaults.items():
    os.environ.setdefault(key, value)


@pytest.fixture(scope="session")
def ai_url(tmp_path_factory):
    default = BACKEND.parent / "ai-service"
    service = Path(os.environ.get("AI_SERVICE_DIR", str(default))).resolve()
    if not (service / "app" / "main.py").is_file():
        pytest.skip(
            "Set AI_SERVICE_DIR to the supplied ai-service directory for live HTTP tests"
        )
    ai_python = os.environ.get("AI_PYTHON")
    if not ai_python:
        pytest.skip("Set AI_PYTHON to the separate AI virtual environment interpreter")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = dict(
        os.environ,
        AI_MODE="mock",
        INTERNAL_TOKEN="integration-test-token",
        PYTHONPATH=str(service),
    )
    log_path = tmp_path_factory.mktemp("ai") / "server.log"
    with log_path.open("w+") as log:
        process = subprocess.Popen(
            [
                ai_python,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=service,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(timeout=1, trust_env=False) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        pytest.fail(log_path.read_text())
                    try:
                        if client.get(url + "/health").status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail("AI service did not start: " + log_path.read_text())
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import worker
from app.config import settings
from app.auth import get_auth_db
from app.db import get_db
from app.main import app
from app.models import Base


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        engine = create_engine(url)
        assert engine.url.database.startswith("alem_test_")
        with engine.begin() as connection:
            connection.execute(
                text("TRUNCATE " + ", ".join(Base.metadata.tables) + " CASCADE")
            )
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def get_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[get_auth_db] = get_session
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "audio"))
    monkeypatch.setattr(settings, "ai_mode", "http")
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()
