from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from alem_contract.audio import MEDIA
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    storage_dir: str
    app_env: Literal["development", "test", "production"] = "development"
    max_upload_mb: int = Field(default=MEDIA["max_upload_mb"], gt=0, le=200)
    max_audio_seconds: int = Field(default=MEDIA["max_audio_seconds"], gt=0, le=1800)
    ai_base_url: AnyHttpUrl
    ai_mode: Literal["mock", "http", "real"]
    ai_internal_token: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=3600, gt=0)
    frontend_origin: AnyHttpUrl
    ai_expected_mode: Literal["mock", "real"] = "real"
    cookie_secure: bool = True
    session_hours: int = Field(default=12, ge=1, le=168)
    worker_lease_seconds: int = Field(default=180, ge=30)
    worker_heartbeat_seconds: int = Field(default=15, ge=1)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_seconds: int = Field(default=10, ge=1)
    upload_limit_per_hour: int = Field(default=20, ge=1)
    max_active_meetings: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def safe_configuration(self):
        if self.worker_heartbeat_seconds * 3 >= self.worker_lease_seconds:
            raise ValueError("worker lease must exceed three heartbeat intervals")
        if self.app_env == "production":
            if not self.cookie_secure or self.frontend_origin.scheme != "https":
                raise ValueError("production requires HTTPS and secure session cookies")
            if self.ai_mode == "mock" or self.ai_expected_mode != "real":
                raise ValueError("production requires real AI")
            if (
                not self.ai_internal_token
                or len(self.ai_internal_token.get_secret_value()) < 32
            ):
                raise ValueError(
                    "production requires an AI_INTERNAL_TOKEN of at least 32 characters"
                )
        return self

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
