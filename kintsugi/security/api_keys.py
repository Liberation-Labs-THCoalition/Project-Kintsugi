"""Per-org API keys (Kintsugi step 3).

A key is ``kin_`` plus ``secrets.token_urlsafe(32)``. It is shown once, at creation, and only its SHA-256 is kept. The
key is high-entropy random, so a slow hash buys nothing; comparison uses ``hmac.compare_digest``. The ``kin_`` prefix
makes a leaked key greppable and recognisable to secret scanners.

The store is a JSON file (``settings.API_KEYS_FILE``, mode 0600) rather than a database table: the framework layer runs
without Postgres (agents, sessions and the Oracle Loop are process-local), and authentication must not depend on a
database that is optional. Writes are atomic (temporary file, then rename) and serialised with an advisory lock, so the
CLI and a running server can share the file.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

Role = Literal["member", "admin"]
ROLES: tuple[str, ...] = ("member", "admin")
PREFIX = "kin_"


@dataclass
class KeyRecord:
    id: str
    org_id: str
    role: str
    label: str
    prefix: str          # the first characters after kin_, for telling keys apart in listings; never the whole key
    key_hash: str        # SHA-256 hex of the full key
    created_at: str
    revoked_at: str | None = None


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KeyStore:
    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(os.path.expanduser(str(path)))
        self._cache: tuple[float, list[KeyRecord]] | None = None

    # --- file handling ---
    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_name(self.path.name + ".lock")
        with open(lock, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _read(self) -> list[KeyRecord]:
        if not self.path.exists():
            return []
        mtime = self.path.stat().st_mtime
        if self._cache and self._cache[0] == mtime:
            return self._cache[1]
        records = [KeyRecord(**r) for r in json.loads(self.path.read_text() or "[]")]
        self._cache = (mtime, records)
        return records

    def _write(self, records: list[KeyRecord]) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump([asdict(r) for r in records], fh, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        self._cache = None

    # --- operations ---
    def create(self, org_id: str, role: str, label: str = "") -> tuple[KeyRecord, str]:
        """Mint a key. Returns (record, plaintext); the plaintext is never stored and cannot be recovered."""
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if not org_id:
            raise ValueError("org_id is required")
        plaintext = PREFIX + secrets.token_urlsafe(32)
        rec = KeyRecord(id=uuid.uuid4().hex[:12], org_id=str(org_id), role=role, label=label,
                        prefix=plaintext[len(PREFIX):len(PREFIX) + 6], key_hash=_hash(plaintext), created_at=_now())
        with self._locked():
            records = list(self._read())
            records.append(rec)
            self._write(records)
        return rec, plaintext

    def lookup(self, plaintext: str) -> KeyRecord | None:
        """The live record for this key, or None (unknown, revoked or malformed alike). Every stored hash is compared,
        in constant time per comparison, so the scan's length does not depend on where a match sits."""
        if not isinstance(plaintext, str) or not plaintext.startswith(PREFIX):
            return None
        digest = _hash(plaintext)
        found = None
        for rec in self._read():
            if hmac.compare_digest(rec.key_hash, digest) and found is None:
                found = rec
        return found if found is not None and found.revoked_at is None else None

    def revoke(self, key_id: str) -> bool:
        with self._locked():
            records = list(self._read())
            hit = False
            for rec in records:
                if rec.id == key_id and rec.revoked_at is None:
                    rec.revoked_at = _now()
                    hit = True
            if hit:
                self._write(records)
        return hit

    def list(self) -> list[KeyRecord]:
        return list(self._read())


_store: KeyStore | None = None


def get_key_store() -> KeyStore:
    """The process-wide store at settings.API_KEYS_FILE (re-created if the setting changes, which tests rely on)."""
    global _store
    from kintsugi.config.settings import settings

    if _store is None or _store.path != Path(os.path.expanduser(settings.API_KEYS_FILE)):
        _store = KeyStore(settings.API_KEYS_FILE)
    return _store
