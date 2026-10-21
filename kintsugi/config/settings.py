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

    # --- LLM Keys (optional) ---
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # --- Model routing ---
    MODEL_ROUTING: dict[str, str] = {
        "haiku": "claude-3-5-haiku-20241022",
        "sonnet": "claude-sonnet-4-20250514",
        "opus": "claude-opus-4-20250514",
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
    SECRET_KEY: str = "CHANGE-ME-in-production"  # not used for API auth (keys below); kept for older callers
    # Per-org API keys: hashes only, minted by `kintsugi keys create` (step 3).
    API_KEYS_FILE: str = "~/.kintsugi/api_keys.json"
    # Actions waiting for, or given, consent: kept on disk so a restart neither approves nor forgets one.
    CONSENT_FILE: str = "~/.kintsugi/consent.json"
    # Who is on call for critical and raid alerts, and everyone's contacts, per org (kintsugi/governance/oncall.py):
    # {"<org>": {"on_call": ["alice"], "contacts": {"alice": [{"channel": "signal", "address": "..."}]},
    #            "ack_window_seconds": 300}}. No file, or no entry for an org, means nobody is on call.
    ONCALL_FILE: str = "~/.kintsugi/oncall.json"
    # On-call alerts sent, acknowledged and escalated: kept on disk so a restart can't forget an escalation.
    ONCALL_ALERTS_FILE: str = "~/.kintsugi/oncall_alerts.json"
    # Whether an on-call message carries the reported area. Off for a deployment whose messenger is a third party it
    # wouldn't trust with a location (Vera, 2026-10-20).
    ONCALL_SEND_AREA: bool = True
    # How often the server checks for on-call alerts whose acknowledgement window has closed.
    ONCALL_TICK_SECONDS: int = 30
    # Auth off is allowed only for local development: with it set, every request not from loopback is refused.
    KINTSUGI_AUTH_DISABLED: bool = False
    KINTSUGI_AUTH_DISABLED_ORG: str = "default"
    # FastAPI's /docs, /redoc and /openapi.json enumerate every route, so they are off unless asked for.
    PUBLIC_DOCS: bool = False
    # Oracle hook destinations, chosen by name through the API: name -> URL. The API can pick a name, never supply a
    # URL. Each URL must be https, or http to a loopback host.
    ORACLE_HOOK_ENDPOINTS: dict[str, str] = {}
    # Append-only JSONL record of admin actions (Oracle mode and endpoint changes, key management).
    AUDIT_LOG_FILE: str = "~/.kintsugi/audit.jsonl"

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

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
