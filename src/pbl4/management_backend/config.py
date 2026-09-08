"""Management Backend configuration.

Loads deployment configuration from environment variables using pydantic-settings.
No production credentials or concrete database URLs are hardcoded as defaults.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    """All configuration for the Management Backend process.

    Values are loaded from environment variables or an optional `.env` file.
    DATABASE_URL must be provided; there is no default database assumed.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Server ───────────────────────────────────────────────────────────────
    backend_host: str = Field(default="127.0.0.1", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")

    # ─── Database ─────────────────────────────────────────────────────────────
    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    # ─── Runtime (MCP/1) ──────────────────────────────────────────────────────
    runtime_host: str = Field(default="127.0.0.1", alias="RUNTIME_HOST")
    runtime_management_port: int | None = Field(default=None, alias="RUNTIME_MANAGEMENT_PORT")

    # ─── Dataset Manager ──────────────────────────────────────────────────────
    dataset_manager_host: str = Field(default="127.0.0.1", alias="DATASET_MANAGER_HOST")
    dataset_manager_port: int | None = Field(default=None, alias="DATASET_MANAGER_PORT")

    # ─── Training Cluster Defaults ────────────────────────────────────────────
    expected_workers: int = Field(default=3, alias="EXPECTED_WORKERS")

    # ─── Logging ──────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ─── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        alias="CORS_ORIGINS",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, v: object) -> object:
        """Allow CORS_ORIGINS to be a comma-separated string in env."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def runtime_management_url(self) -> str | None:
        if self.runtime_management_port is None:
            return None
        return f"{self.runtime_host}:{self.runtime_management_port}"

    @property
    def dataset_manager_base_url(self) -> str | None:
        if self.dataset_manager_port is None:
            return None
        return f"http://{self.dataset_manager_host}:{self.dataset_manager_port}"


@lru_cache(maxsize=1)
def get_settings() -> BackendSettings:
    """Return the cached application settings singleton."""
    return BackendSettings()
