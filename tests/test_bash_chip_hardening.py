"""BashSkillChip and the direct-execution route, after Vera's 2026-09-24 review.

The chip had no behavioural tests at all, so nothing noticed that a caller could
approve its own command, that the safe tier handed the whole string to a shell,
or that paths were not confined to the workspace. Each test here fails on the
pre-fix code for the reason its name gives.
"""
import asyncio
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import kintsugi.api.routes.skills as skills_route
from kintsugi.skills.base import BaseSkillChip, SkillContext, SkillDomain, SkillRequest, SkillResponse
from kintsugi.skills.core_ops.bash_executor import BashSkillChip


def _ctx():
    return SkillContext(org_id="test", user_id="test", platform="test", metadata={})


def _req(cmd, **params):
    return SkillRequest(intent="shell", entities={}, raw_input=cmd, parameters=params)


@pytest.fixture
def chip(tmp_path):
    return BashSkillChip(workspace_dir=str(tmp_path / "ws"))


@pytest.fixture
def spawns(monkeypatch):
    """Record every subprocess the chip tries to start; run the exec ones for real."""
    calls = {"shell": [], "exec": []}
    real_exec = asyncio.create_subprocess_exec

    async def fake_shell(cmd, **kw):
        calls["shell"].append(cmd)
        raise AssertionError("the chip must not start a shell")

    async def spy_exec(*argv, **kw):
        calls["exec"].append((argv, kw))
        return await real_exec(*argv, **kw)

    monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy_exec)
    return calls


def test_a_caller_cannot_approve_its_own_command(chip, spawns):
    resp = asyncio.run(chip.handle(_req("python3 --version", approved=True), _ctx()))
    assert resp.requires_consensus and not resp.success
    assert spawns["exec"] == [] and spawns["shell"] == []


def test_a_safe_command_runs_without_a_shell(chip, spawns):
    resp = asyncio.run(chip.handle(_req("pwd"), _ctx()))
    assert resp.success, resp.content
    assert spawns["shell"] == [] and spawns["exec"][0][0] == ("pwd",)
    assert str(chip.workspace.resolve()) in resp.content


def test_the_safe_tier_stays_inside_the_workspace(chip, tmp_path):
    (chip.workspace / "notes.txt").write_text("hi\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("not yours\n")
    assert chip.classify_command("head notes.txt").tier == "always_allow"
    assert chip.classify_command(f"head {outside}").tier == "ask"
    assert chip.classify_command("head ../outside.txt").tier == "ask"
    assert chip.classify_command("head ~/outside.txt").tier == "ask"


def test_a_symlink_out_of_the_workspace_is_outside(chip, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (chip.workspace / "link").symlink_to(tmp_path / "elsewhere")
    assert chip.classify_command("ls link").tier == "ask"


def test_long_options_and_option_paths_leave_the_safe_tier(chip):
    assert chip.classify_command("ls -la").tier == "always_allow"
    assert chip.classify_command("ls --all").tier == "ask"
    assert chip.classify_command("sort -o/tmp/x notes.txt").tier == "ask"


def test_a_pipeline_is_not_a_safe_command(chip, spawns):
    assert chip.classify_command("ls | wc -l").tier == "ask"
    resp = asyncio.run(chip.handle(_req("ls | wc -l"), _ctx()))
    assert resp.requires_consensus and spawns["exec"] == [] and spawns["shell"] == []


def test_the_subprocess_gets_a_minimal_environment(chip, spawns, monkeypatch):
    monkeypatch.setenv("KINTSUGI_TEST_SENTINEL", "server-only")
    asyncio.run(chip.handle(_req("pwd"), _ctx()))
    env = spawns["exec"][0][1]["env"]
    assert "KINTSUGI_TEST_SENTINEL" not in env
    assert env["HOME"] == str(chip.workspace) and "PATH" in env


class _Registry:
    def __init__(self, chip):
        self.chip = chip

    def get(self, name):
        return self.chip if name == self.chip.name else None


class _EchoParams(BaseSkillChip):
    name = "echo_params"
    domain = SkillDomain.OPERATIONS
    description = "records the parameters it receives"
    version = "0"
    capabilities = []

    async def handle(self, request, context):
        self.seen = dict(request.parameters)
        return SkillResponse(content="ok", success=True)


def _client(monkeypatch, chip):
    monkeypatch.setattr(skills_route, "get_registry", lambda: _Registry(chip))
    app = FastAPI()
    app.include_router(skills_route.router)
    return TestClient(app)


def test_the_direct_route_refuses_shell_capable_chips(chip, spawns, monkeypatch):
    r = _client(monkeypatch, chip).post("/api/v1/skills/bash_executor/execute", json={"raw_input": "pwd"})
    assert r.status_code == 403
    assert spawns["exec"] == [] and spawns["shell"] == []


def test_the_direct_route_strips_reserved_parameters(monkeypatch):
    echo = _EchoParams()
    r = _client(monkeypatch, echo).post("/api/v1/skills/echo_params/execute",
                                        json={"raw_input": "x", "parameters": {"approved": True, "k": 1}})
    assert r.status_code == 200
    assert echo.seen == {"k": 1}
