"""
MUTAGEN configuration management.

Uses pydantic-settings for validated, type-safe configuration.
Environment variables take precedence over .env file values.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIProvider(str, Enum):
    """Supported AI provider backends."""
    GEMINI = "gemini"
    GROQ = "groq"
    FAKE = "fake"  # Deterministic test provider only


class OptimizationObjective(str, Enum):
    """Optimization objective types."""
    SPEED = "speed"
    MEMORY = "memory"
    BALANCED = "balanced"


class LogLevel(str, Enum):
    """Logging levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class MutagenSettings(BaseSettings):
    """
    Central application configuration.

    Values are loaded from environment variables (prefixed with MUTAGEN_)
    and an optional .env file. Environment variables always take precedence.
    """

    model_config = SettingsConfigDict(
        env_prefix="MUTAGEN_",
        env_file=(".env", str(Path(__file__).resolve().parents[2] / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── AI Provider ──────────────────────────────────────────
    ai_provider: AIProvider = Field(
        default=AIProvider.GROQ,
        description="AI provider backend to use for mutation generation.",
    )
    ai_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Model identifier for the configured AI provider.",
    )
    gemini_api_key: Optional[str] = Field(
        default=None,
        alias="GEMINI_API_KEY",
        description="API key for Google Gemini. Set via GEMINI_API_KEY env var.",
    )
    groq_api_key: Optional[str] = Field(
        default=None,
        alias="GROQ_API_KEY",
        description="API key for Groq. Set via GROQ_API_KEY env var.",
    )
    groq_max_tokens: Optional[int] = Field(
        default=None,
        alias="GROQ_MAX_TOKENS",
        description="Maximum completion tokens for Groq API calls. Defaults to model maximum up to 16384.",
    )

    # ── Authentication & Security ────────────────────────────
    jwt_secret_key: str = Field(
        default="mutagen-secret-key-change-in-production-must-be-secure-32bytes",
        description="Secret key for signing JWT tokens.",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT algorithm.",
    )
    jwt_access_token_expire_minutes: int = Field(
        default=60,
        ge=1,
        description="Access token expiration time in minutes.",
    )
    jwt_refresh_token_expire_days: int = Field(
        default=30,
        ge=1,
        description="Refresh token expiration time in days.",
    )
    credentials_path: Optional[Path] = Field(
        default=None,
        description="Custom path to store credentials file for CLI authentication.",
    )

    # ── Database ─────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+psycopg://mutagen:mutagen@localhost:5432/mutagen",
        description="PostgreSQL connection URL.",
    )

    # ── Redis ────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for Celery broker.",
    )

    # ── Logging ──────────────────────────────────────────────
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Application log level.",
    )

    # ── Artifact Storage ─────────────────────────────────────
    artifact_dir: Path = Field(
        default=Path("./artifacts"),
        description="Directory for storing code artifacts.",
    )

    # ── Evolution Defaults ───────────────────────────────────
    max_generations: int = Field(default=5, ge=1, le=100)
    population_size: int = Field(default=4, ge=1, le=20)
    benchmark_repetitions: int = Field(default=5, ge=1, le=100)
    execution_timeout: int = Field(default=30, ge=1, le=600, description="Seconds")
    memory_limit: int = Field(default=256, ge=32, le=4096, description="MB")
    max_source_size: int = Field(default=1_048_576, ge=1024, description="Bytes")
    max_candidates_per_generation: int = Field(default=6, ge=1, le=20)

    # ── Sandbox ──────────────────────────────────────────────
    sandbox_image: str = Field(default="python:3.11-slim")
    sandbox_network_disabled: bool = Field(default=True)
    sandbox_cpu_quota: int = Field(default=50_000)
    sandbox_memory_limit: int = Field(default=268_435_456, description="Bytes")
    sandbox_pids_limit: int = Field(default=64, ge=1, le=512)

    @field_validator("artifact_dir")
    @classmethod
    def resolve_artifact_dir(cls, v: Path) -> Path:
        target = (Path(__file__).resolve().parents[2] / v).resolve() if not v.is_absolute() else v.resolve()
        target.mkdir(parents=True, exist_ok=True)
        return target

    @model_validator(mode="after")
    def validate_provider_config(self) -> "MutagenSettings":
        """Warn if Gemini is selected but API key is missing."""
        # We don't raise here — we let commands that need AI check this.
        return self

    def ai_configured(self) -> bool:
        """Check whether the AI provider has the needed credentials."""
        if self.ai_provider == AIProvider.GROQ:
            return bool(self.groq_api_key)
        if self.ai_provider == AIProvider.GEMINI:
            return bool(self.gemini_api_key)
        if self.ai_provider == AIProvider.FAKE:
            return True
        return False

    def require_ai(self) -> None:
        """Raise if AI provider is not configured."""
        from mutagen.exceptions import MutagenConfigError

        if not self.ai_configured():
            key_name = "GROQ_API_KEY" if self.ai_provider == AIProvider.GROQ else "GEMINI_API_KEY"
            raise MutagenConfigError(
                f"AI provider '{self.ai_provider.value}' is not configured. "
                f"Set the required API key ({key_name}) in your environment or .env file."
            )


# ── Singleton accessor ────────────────────────────────────────
_settings: Optional[MutagenSettings] = None


def get_settings() -> MutagenSettings:
    """Return the cached application settings singleton."""
    global _settings
    if _settings is None:
        _settings = MutagenSettings()
    return _settings


def reset_settings() -> None:
    """Reset settings singleton (used in tests)."""
    global _settings
    _settings = None
