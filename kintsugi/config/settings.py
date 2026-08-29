"""Kintsugi configuration via environment / .env file."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://kintsugi:kintsugi@localhost:5432/kintsugi"

    # --- Deployment ---
    DEPLOYMENT_TIER: Literal["seed", "sprout", "grove"] = "sprout"

    # --- Embeddings ---
    EMBEDDING_MODE: Literal["local", "api"] = "local"
    EMBEDDING_MODEL: str = "all-mpnet-base-v2"

    # --- LLM auth ---
    # Preferred: a long-lived OAuth token from `claude setup-token`, tied to
    # a Claude Pro/Max/Team/Enterprise subscription (verified working via
    # AsyncAnthropic(auth_token=...) this session). Falls back to a
    # standard Console API key if unset.
    CLAUDE_CODE_OAUTH_TOKEN: str = ""
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # --- Model routing ---
    # Keys are tier slots (FAST/BALANCED/POWERFUL), not literal model families.
    MODEL_ROUTING: dict[str, str] = {
        "haiku": "claude-haiku-4-5",
        "sonnet": "claude-sonnet-4-5",
        "opus": "claude-opus-4-5",
    }

    # --- Shadow / governance ---
    KINTSUGI_SHADOW_ENABLED: bool = False

    # --- Oracle Loop (Project Oracle detection pipeline) ---
    # off: skip review | observe: record verdicts | enforce: block flagged responses
    ORACLE_MODE: Literal["off", "observe", "enforce"] = "observe"
    # HTTP endpoint of a running Oracle harness; empty = no external hook
    ORACLE_ENDPOINT: str = ""

    # --- Framework layer ---
    PERSONALITY_DIR: str = ""  # empty = kintsugi/config/personalities
    DASHBOARD_ENABLED: bool = True
    MAX_AGENTS: int = 64

    # --- Shield budgets ---
    SHIELD_BUDGET_PER_SESSION: float = 5.0
    SHIELD_BUDGET_PER_DAY: float = 50.0

    # --- Observability ---
    OTEL_EXPORTER_ENDPOINT: str = ""

    # --- Redis / Celery ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Auth ---
    SECRET_KEY: str = "CHANGE-ME-in-production"

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # --- Memory: temporal tree (h-mem-temporal) ---
    TEMPORAL_TREE_DB_PATH: str = "temporal_tree.db"

    # --- Memory: knowledge graph (spaCy NER model for entity extraction) ---
    KG_SPACY_MODEL: str = "en_core_web_md"

    @model_validator(mode="after")
    def _auto_shadow(self) -> "Settings":
        if self.DEPLOYMENT_TIER == "grove":
            self.KINTSUGI_SHADOW_ENABLED = True
        return self

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _fix_pg_scheme(cls, v: str) -> str:
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


settings = Settings()
