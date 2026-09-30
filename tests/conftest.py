"""Shared fixtures (step 3): every test gets its own API-key store and audit log, never ~/.kintsugi, with auth on;
`make_headers` mints a key there and returns the Authorization header for it."""

from __future__ import annotations

import pytest

from kintsugi.config.settings import settings
from kintsugi.security.api_keys import get_key_store


@pytest.fixture(autouse=True)
def _isolated_auth_files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "API_KEYS_FILE", str(tmp_path / "api_keys.json"))
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(settings, "KINTSUGI_AUTH_DISABLED", False)


def mint(role: str = "admin", org: str = "default", label: str = "test") -> dict[str, str]:
    _, key = get_key_store().create(org, role, label)
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def make_headers():
    return mint


@pytest.fixture
def admin_headers():
    return mint("admin")
