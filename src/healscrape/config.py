from __future__ import annotations

import os
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _expand_path(p: str | Path) -> Path:
    return Path(os.path.expanduser(str(p))).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HEALSCRAPE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default_factory=lambda: _expand_path("~/.healscrape"))
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "HEALSCRAPE_DATABASE_URL"),
    )

    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "HEALSCRAPE_GEMINI_API_KEY"),
    )
    gemini_model: str = Field(
        default="gemini-2.0-flash",
        validation_alias=AliasChoices("HEALSCRAPE_GEMINI_MODEL", "GEMINI_MODEL"),
    )

    http_timeout_s: float = 30.0
    max_retries: int = 4
    rate_limit_rps: float = 2.0
    max_concurrent_fetches: int = 4

    min_promotion_confidence: float = 0.85
    llm_max_input_chars: int = 12000

    user_agent: str = "healscrape/0.1 (+https://example.invalid/healscrape)"

    @field_validator("data_dir", mode="before")
    @classmethod
    def _data_dir(cls, v: str | Path) -> Path:
        return _expand_path(v)

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.data_dir / "healscrape.db"
        return f"sqlite:///{db_path.as_posix()}"


def load_settings() -> Settings:
    return Settings()
