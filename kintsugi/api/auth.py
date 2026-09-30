"""Who is calling: the principal dependency (Kintsugi step 3).

Every router except health is included with ``dependencies=[Depends(require_principal)]`` in ``main.py``, and a
route-table test fails if any route escapes it. A dependency rather than a middleware, because a middleware cannot hand
a typed principal to a handler, and it can sit unmounted without anyone noticing: that is how ``AuthMiddleware`` spent
its life.

- The key decides the org. A body, query or path ``org_id`` is accepted only if it equals the key's org (for one
  release, for compatibility); a mismatch is 403. ``user_id`` is audit metadata and never grants anything.
- Two roles: ``member`` and ``admin``. Admin-grade actions depend on ``require_admin``.
- Unknown, revoked and malformed keys all get the same 401 body.
- ``KINTSUGI_AUTH_DISABLED=1`` is for local development only: every request not from loopback is refused.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

from fastapi import Depends, HTTPException, Request, status

from kintsugi.config.settings import settings
from kintsugi.security.api_keys import get_key_store

UNAUTHORIZED = "invalid or missing API key"


@dataclass(frozen=True)
class Principal:
    org_id: str
    key_id: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=UNAUTHORIZED,
                         headers={"WWW-Authenticate": "Bearer"})


def require_principal(request: Request) -> Principal:
    if settings.KINTSUGI_AUTH_DISABLED:
        client = request.client.host if request.client else None
        if not is_loopback(client):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="auth is disabled, which is allowed for loopback clients only")
        return Principal(org_id=settings.KINTSUGI_AUTH_DISABLED_ORG, key_id="auth-disabled", role="admin")
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized()
    rec = get_key_store().lookup(token.strip())
    if rec is None:
        raise _unauthorized()
    return Principal(org_id=rec.org_id, key_id=rec.id, role=rec.role)


def require_admin(principal: Principal = Depends(require_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin key required")
    return principal


def resolve_org(principal: Principal, requested: object | None) -> str:
    """The org a request acts on: always the key's. A requested org that differs is refused, not silently replaced."""
    if requested is None or str(requested) == "":
        return principal.org_id
    if str(requested) != principal.org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="org_id does not match the API key's organization")
    return principal.org_id


def audit(principal: Principal, action: str, **detail) -> None:
    """Append one JSON line per admin action. Failing to audit fails the action (the caller sees a 500)."""
    path = Path(os.path.expanduser(settings.AUDIT_LOG_FILE))
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "action": action, "key_id": principal.key_id,
           "org_id": principal.org_id, "role": principal.role, **detail}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
