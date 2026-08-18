"""Application configuration.

All configuration is externalized via environment variables (12-factor). Settings are parsed and
validated once at import time and injected everywhere via :func:`get_settings`, so no module reads
``os.environ`` directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Typed, validated application settings sourced from the environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application ----
    app_env: Environment = "development"
    app_name: str = "API Traffic Management Platform"
    log_level: str = "INFO"
    log_json: bool = False
    debug: bool = True

    # ---- Server ----
    host: str = "0.0.0.0"
    port: int = 8000

    # ---- Database ----
    database_url: str = "postgresql+asyncpg://apitraffic:apitraffic@localhost:5432/apitraffic"

    # ---- Redis ----
    redis_url: str = "redis://localhost:6379/0"

    # ---- Security / Auth ----
    jwt_secret: str = "insecure-development-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 1_209_600
    refresh_cookie_secure: bool = False

    # ---- Gateway ----
    gateway_upstream_timeout_seconds: float = 15.0
    gateway_max_body_bytes: int = 1_048_576

    # ---- Auth rate limiting ----
    auth_rate_limit_per_minute: int = 10

    # ---- CORS ----
    # NoDecode: keep pydantic-settings from JSON-decoding the env string; we split it ourselves.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # ---- Telemetry ----
    telemetry_enabled: bool = True
    # Optional forwarding to the Observability platform (Project B). When a URL is set, the outbox
    # publisher delivers via an HMAC-signed HTTP POST instead of the default LoggingSink. The secret
    # is SEPARATE from JWT — it protects the service-to-service ingestion boundary.
    telemetry_forward_url: str = ""
    telemetry_forward_hmac_secret: str = ""
    telemetry_forward_timeout_seconds: float = 10.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string (env-friendly) or a real list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sync_database_url(self) -> str:
        """Synchronous URL (psycopg-style) used by Alembic migrations."""
        return self.database_url.replace("+asyncpg", "").replace("postgresql://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton (cached)."""
    return Settings()
