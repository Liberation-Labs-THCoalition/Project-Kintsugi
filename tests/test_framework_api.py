"""API-level tests for the framework routes and dashboard."""

from __future__ import annotations

import httpx
import pytest

from kintsugi.main import app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_spawn_message_stop_via_api(client):
    resp = await client.post("/api/v1/agents", json={"personality": "default"})
    assert resp.status_code == 201, resp.text
    agent = resp.json()
    assert agent["state"] == "idle"

    resp = await client.get("/api/v1/agents")
    assert any(a["id"] == agent["id"] for a in resp.json()["agents"])

    resp = await client.post(
        f"/api/v1/agents/{agent['id']}/messages", json={"message": "hello there"}
    )
    assert resp.status_code == 200, resp.text
    turn = resp.json()
    assert turn["response"]
    assert "oracle" in turn and "routing" in turn

    resp = await client.delete(f"/api/v1/agents/{agent['id']}")
    assert resp.json()["state"] == "stopped"


async def test_spawn_unknown_personality_404(client):
    resp = await client.post("/api/v1/agents", json={"personality": "does-not-exist"})
    assert resp.status_code == 404


async def test_session_flow_via_api(client):
    resp = await client.post("/api/v1/sessions", json={"personality": "default"})
    assert resp.status_code == 201, resp.text
    session = resp.json()

    resp = await client.post(
        f"/api/v1/sessions/{session['id']}/messages", json={"message": "what skills do you have?"}
    )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == session["id"]

    resp = await client.get(f"/api/v1/sessions/{session['id']}")
    body = resp.json()
    assert body["turns"] == 1
    assert len(body["history"]) == 2

    resp = await client.delete(f"/api/v1/sessions/{session['id']}")
    assert resp.json()["closed"] is True

    # closed session refuses messages
    resp = await client.post(
        f"/api/v1/sessions/{session['id']}/messages", json={"message": "hi"}
    )
    assert resp.status_code == 409


async def test_personalities_listed(client):
    resp = await client.get("/api/v1/agents/personalities")
    names = [p["name"] for p in resp.json()["personalities"]]
    assert "default" in names
    assert "guardian" in names  # shipped sample
    assert "researcher" in names  # TOML sample


async def test_skills_listing_and_unknown_skill(client):
    resp = await client.get("/api/v1/skills")
    assert resp.status_code == 200
    assert "skills" in resp.json()

    resp = await client.get("/api/v1/skills/definitely-not-a-skill")
    assert resp.status_code == 404

    resp = await client.post(
        "/api/v1/skills/definitely-not-a-skill/execute", json={"raw_input": "x"}
    )
    assert resp.status_code == 404


async def test_oracle_status_and_mode_switch(client):
    resp = await client.get("/api/v1/oracle/status")
    assert resp.status_code == 200
    original_mode = resp.json()["mode"]

    resp = await client.put("/api/v1/oracle/mode", json={"mode": "enforce"})
    assert resp.json()["mode"] == "enforce"
    resp = await client.put("/api/v1/oracle/mode", json={"mode": "banana"})
    assert resp.status_code == 422  # pydantic literal validation

    await client.put("/api/v1/oracle/mode", json={"mode": original_mode})


async def test_oracle_verdicts_populated_by_messages(client):
    resp = await client.post("/api/v1/agents", json={"personality": "default"})
    agent_id = resp.json()["id"]
    await client.post(f"/api/v1/agents/{agent_id}/messages", json={"message": "ping"})

    resp = await client.get("/api/v1/oracle/verdicts")
    verdicts = resp.json()["verdicts"]
    assert any(v["agent_id"] == agent_id for v in verdicts)
    await client.delete(f"/api/v1/agents/{agent_id}")


async def test_events_recent(client):
    resp = await client.get("/api/v1/events/recent")
    assert resp.status_code == 200
    events = resp.json()["events"]
    # earlier tests generated agent/session events through the shared bus
    assert any(e["type"].startswith("agent.") for e in events)


async def test_dashboard_renders(client):
    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    assert "kintsugi" in resp.text.lower()

    for partial in ("agents", "sessions", "oracle", "skills"):
        resp = await client.get(f"/dashboard/partials/{partial}")
        assert resp.status_code == 200, partial


async def test_root_redirects_to_dashboard(client):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/dashboard"
