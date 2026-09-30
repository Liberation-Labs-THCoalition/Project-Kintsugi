"""Step 3: authentication, org scoping and admin gating (Vera's review of c5d5848, 2026-09-29; CC's design letter).

The route-table test is the check Vera ran by hand, made permanent: any route added later without the principal
dependency fails here.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import httpx
import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from typer.testing import CliRunner

from kintsugi.api.auth import Principal, require_principal, resolve_org
from kintsugi.config.settings import settings
from kintsugi.main import app
from kintsugi.security.api_keys import KeyStore, get_key_store
from tests.conftest import mint

PUBLIC_PATHS = {"/api/health", "/"}          # health, and the bare redirect to /dashboard


def _has_dep(dependant, fn) -> bool:
    return any(d.call is fn or _has_dep(d, fn) for d in dependant.dependencies)


def test_every_route_requires_a_principal_except_the_public_ones():
    checked = 0
    for route in app.routes:
        if not isinstance(route, (APIRoute, APIWebSocketRoute)):
            continue                                              # the /static file mount serves CSS and JS only
        if route.path in PUBLIC_PATHS:
            continue
        assert _has_dep(route.dependant, require_principal), f"{route.path} is reachable without a key"
        checked += 1
    assert checked >= 30                                          # the check saw the real route table


def test_the_public_routes_are_only_health_and_the_redirect():
    public = {r.path for r in app.routes if isinstance(r, (APIRoute, APIWebSocketRoute))
              and not _has_dep(r.dependant, require_principal)}
    assert public == PUBLIC_PATHS


def test_cors_sends_no_credentials_and_allows_only_two_headers():
    from starlette.middleware.cors import CORSMiddleware

    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    assert cors.kwargs["allow_credentials"] is False
    assert sorted(cors.kwargs["allow_headers"]) == ["Authorization", "Content-Type"]


def test_docs_are_off_by_default():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert not paths & {"/docs", "/redoc", "/openapi.json"}


# ---------- over HTTP, against the real app ----------
@pytest.fixture
def call():
    async def _call(method, path, headers=None, client=("198.51.100.7", 4000), **kw):
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers or {}) as c:
            return await c.request(method, path, **kw)
    return _call


async def test_no_key_malformed_key_and_revoked_key_get_the_same_401(call):
    rec, key = get_key_store().create("default", "admin")
    get_key_store().revoke(rec.id)
    bodies = set()
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": f"Basic {key}"},
                    {"Authorization": f"Bearer {key}"}, {"Authorization": "Bearer kin_" + "x" * 43}):
        r = await call("GET", "/api/v1/agents", headers=headers)
        assert r.status_code == 401
        bodies.add(r.text)
    assert len(bodies) == 1


async def test_a_live_key_under_any_scheme_but_bearer_is_refused(call):
    """The scheme is checked on its own: a valid key sent as Basic (or bare) gets the same 401."""
    _, live = get_key_store().create("default", "admin")
    assert (await call("GET", "/api/v1/agents", headers={"Authorization": f"Bearer {live}"})).status_code == 200
    for headers in ({"Authorization": f"Basic {live}"}, {"Authorization": f"Token {live}"},
                    {"Authorization": live}):
        assert (await call("GET", "/api/v1/agents", headers=headers)).status_code == 401, headers


async def test_health_needs_no_key(call):
    assert (await call("GET", "/api/health")).status_code == 200


@pytest.mark.parametrize("method,path,body", [
    ("PUT", "/api/v1/oracle/mode", {"mode": "off"}),
    ("PUT", "/api/v1/oracle/endpoint", {"name": ""}),
    ("POST", "/api/v1/agents/personalities/reload", None),
    ("POST", "/api/v1/skills/plugins/anything/load", None),
    ("POST", "/api/v1/skills/plugins/anything/reload", None),
    ("DELETE", "/api/v1/skills/plugins/anything", None),
    ("GET", "/api/v1/events/recent", None),
    ("GET", "/dashboard", None),
    ("POST", "/dashboard/actions/oracle-mode", None),
    ("PUT", "/api/config/values", {"values": {}}),
    ("POST", "/api/config/init", {"org_name": "x", "org_type": "cooperative"}),
])
async def test_a_member_key_is_refused_on_admin_routes(call, method, path, body):
    r = await call(method, path, headers=mint("member"), json=body)
    assert r.status_code == 403


async def test_another_orgs_agents_and_sessions_read_as_not_found(call):
    a, b = mint("member", org="org-a"), mint("member", org="org-b")
    r = await call("POST", "/api/v1/agents", headers=a, json={"personality": "default"})
    assert r.status_code == 201
    agent_id = r.json()["id"]
    listed = await call("GET", "/api/v1/agents", headers=b)
    assert agent_id not in {x["id"] for x in listed.json()["agents"]}
    for method, path, body in (("GET", f"/api/v1/agents/{agent_id}", None),
                               ("POST", f"/api/v1/agents/{agent_id}/messages", {"message": "hi"}),
                               ("DELETE", f"/api/v1/agents/{agent_id}", None),
                               ("POST", "/api/v1/sessions", {"agent_id": agent_id})):
        assert (await call(method, path, headers=b, json=body)).status_code == 404, path
    assert (await call("GET", f"/api/v1/agents/{agent_id}", headers=a)).status_code == 200
    s = await call("POST", "/api/v1/sessions", headers=a, json={"agent_id": agent_id})
    assert s.status_code == 201
    sid = s.json()["id"]
    assert (await call("GET", f"/api/v1/sessions/{sid}", headers=b)).status_code == 404
    assert sid not in {x["id"] for x in (await call("GET", "/api/v1/sessions", headers=b)).json()["sessions"]}
    assert (await call("DELETE", f"/api/v1/agents/{agent_id}", headers=a)).status_code == 200


async def test_a_body_org_that_is_not_the_keys_org_is_refused(call):
    from kintsugi.skills.bootstrap import register_builtin_chips

    register_builtin_chips()                               # content_drafter: a real chip that is not shell-capable
    a = mint("member", org="org-a")
    for path, body in (("/api/v1/agents", {"personality": "default", "org_id": "org-b"}),
                       ("/api/v1/sessions", {"org_id": "org-b"}),
                       ("/api/v1/skills/content_drafter/execute", {"raw_input": "x", "org_id": "org-b"})):
        r = await call("POST", path, headers=a, json=body)
        assert r.status_code == 403, path
        assert "does not match" in r.json()["detail"]
    ok = await call("POST", "/api/v1/agents", headers=a, json={"personality": "default", "org_id": "org-a"})
    assert ok.status_code == 201 and ok.json().get("org_id", "org-a") == "org-a"


def test_resolve_org():
    p = Principal(org_id="org-a", key_id="k", role="member")
    assert resolve_org(p, None) == "org-a" and resolve_org(p, "") == "org-a" and resolve_org(p, "org-a") == "org-a"
    with pytest.raises(Exception) as exc:
        resolve_org(p, "org-b")
    assert getattr(exc.value, "status_code", None) == 403


# ---------- the Oracle hook ----------
async def test_oracle_endpoint_is_chosen_by_allowlisted_name_and_audited(call, monkeypatch):
    monkeypatch.setattr(settings, "ORACLE_HOOK_ENDPOINTS", {"oracle": "https://oracle.example/review",
                                                            "plain": "http://oracle.example/review",
                                                            "local": "http://127.0.0.1:8900/review"})
    admin = mint("admin")
    r = await call("PUT", "/api/v1/oracle/endpoint", headers=admin, json={"endpoint": "https://evil.example/steal"})
    assert r.status_code == 422                                   # the old shape, a raw URL, is gone
    r = await call("PUT", "/api/v1/oracle/endpoint", headers=admin, json={"name": "not-listed"})
    assert r.status_code == 422
    r = await call("PUT", "/api/v1/oracle/endpoint", headers=admin, json={"name": "plain"})
    assert r.status_code == 400                                   # plaintext to a remote host is refused
    for name in ("oracle", "local", ""):
        assert (await call("PUT", "/api/v1/oracle/endpoint", headers=admin, json={"name": name})).status_code == 200
    r = await call("PUT", "/api/v1/oracle/mode", headers=admin, json={"mode": "observe"})
    assert r.status_code == 200
    rows = [json.loads(x) for x in Path(settings.AUDIT_LOG_FILE).read_text().splitlines()]
    actions = [(x["action"], x.get("new")) for x in rows]
    assert ("oracle.endpoint", "oracle") in actions and ("oracle.endpoint", "local") in actions
    assert ("oracle.endpoint", "(detached)") in actions and ("oracle.mode", "observe") in actions
    assert all(x["key_id"] and x["role"] == "admin" for x in rows)
    names = (await call("GET", "/api/v1/oracle/endpoints", headers=mint("member"))).json()["endpoints"]
    assert names == ["local", "oracle", "plain"]                  # names only, never URLs


async def test_the_hook_never_follows_a_redirect(monkeypatch):
    from kintsugi.oracle import hooks

    seen, kwargs = [], {}

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://evil.example/steal"})

    real = httpx.AsyncClient

    class Recording(real):
        def __init__(self, **kw):
            kwargs.update(kw)
            super().__init__(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(hooks.httpx, "AsyncClient", Recording)
    hook = hooks.HTTPOracleHook("https://oracle.example/review")

    class Turn:
        def to_dict(self):
            return {"text": "x"}

    verdict = await hook.review(Turn())
    assert kwargs.get("follow_redirects") is False
    assert seen == ["https://oracle.example/review"]              # the redirect target was never requested
    assert verdict.status == "error"


def test_hook_urls_must_be_https_or_loopback():
    from kintsugi.oracle.hooks import check_hook_url

    for ok in ("https://oracle.example/r", "http://127.0.0.1:8900/r", "http://localhost:8900/r", "http://[::1]/r"):
        check_hook_url(ok)
    for bad in ("http://oracle.example/r", "ftp://oracle.example/r", "https:///nohost", "oracle.example"):
        with pytest.raises(ValueError):
            check_hook_url(bad)


# ---------- auth disabled ----------
async def test_auth_disabled_serves_loopback_only(call, monkeypatch):
    monkeypatch.setattr(settings, "KINTSUGI_AUTH_DISABLED", True)
    assert (await call("GET", "/api/v1/agents", client=("198.51.100.7", 4000))).status_code == 403
    assert (await call("GET", "/api/v1/agents", client=("127.0.0.1", 4000))).status_code == 200


# ---------- the key store and the CLI ----------
def test_key_store_keeps_only_a_hash(tmp_path):
    store = KeyStore(tmp_path / "keys.json")
    rec, key = store.create("org-a", "member", "label")
    text = (tmp_path / "keys.json").read_text()
    assert key.startswith("kin_") and key not in text and key[4:] not in text
    assert stat.S_IMODE((tmp_path / "keys.json").stat().st_mode) == 0o600
    assert store.lookup(key).id == rec.id
    assert store.lookup(key + "x") is None and store.lookup("nope") is None and store.lookup(None) is None
    assert store.revoke(rec.id) and store.lookup(key) is None and not store.revoke(rec.id)
    with pytest.raises(ValueError):
        store.create("org-a", "root")


def test_cli_mints_lists_and_revokes():
    from kintsugi.cli import _register_subcommands
    from kintsugi.cli import app as cli_app

    _register_subcommands()
    runner = CliRunner()
    r = runner.invoke(cli_app, ["keys", "create", "--org", "org-a", "--role", "admin", "--label", "boot"])
    assert r.exit_code == 0
    key = r.output.strip().splitlines()[-1]
    assert key.startswith("kin_") and get_key_store().lookup(key).role == "admin"
    listing = runner.invoke(cli_app, ["keys", "list"]).output
    rec = get_key_store().lookup(key)
    assert "org=org-a" in listing and key not in listing and rec.key_hash not in listing   # the prefix only
    assert f"kin_{rec.prefix}..." in listing
    key_id = get_key_store().lookup(key).id
    assert runner.invoke(cli_app, ["keys", "revoke", key_id]).exit_code == 0
    assert get_key_store().lookup(key) is None
    assert runner.invoke(cli_app, ["keys", "create", "--org", "o", "--role", "root"]).exit_code == 2
    actions = [json.loads(x)["action"] for x in Path(settings.AUDIT_LOG_FILE).read_text().splitlines()]
    assert actions == ["keys.create", "keys.revoke"]
