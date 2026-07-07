"""Tests for OracleMonitorChip — Oracle Loop integration point.

Uses a fake OracleLoop (no torch/transformers dependency) so these tests
exercise the Kintsugi-side decision routing without needing a real model.
"""

import pytest

from kintsugi.governance.consensus import ConsensusGate, ConsentStatus
from kintsugi.skills.base import SkillContext, SkillRequest
from kintsugi.skills.oracle_monitor import OracleMonitorChip, OracleMonitorConfig


def make_report(decision, status="GREEN", pathway="none", signal_strength=0.0, verdict=None):
    return {
        "detection": {
            "status": status,
            "pathway": pathway,
            "signal_strength": signal_strength,
        },
        "decision": decision,
        "correction": None,
        "verification": {"verdict": verdict} if verdict else None,
        "generation": {"n_tokens": 5},
        "stats": {},
    }


class FakeOracleLoop:
    """Stands in for oracle_harness.loop.OracleLoop in tests."""

    def __init__(self, response_text, report):
        self._response_text = response_text
        self._report = report
        self.calls = []

    def process(self, messages, suppress_think=False, seed=None, **kwargs):
        self.calls.append({"messages": messages, "suppress_think": suppress_think, "seed": seed})
        return self._response_text, self._report


@pytest.fixture
def context():
    return SkillContext(org_id="org_test", user_id="user_test", session_id="session_1")


def make_chip(response_text, report, **kwargs):
    loop = FakeOracleLoop(response_text, report)
    chip = OracleMonitorChip(oracle_loop=loop, consensus_gate=ConsensusGate(), **kwargs)
    return chip, loop


class TestOracleMonitorChip:
    def test_no_backend_raises_on_use(self, context):
        chip = OracleMonitorChip()
        with pytest.raises(RuntimeError, match="cannot monitor Anthropic API"):
            chip._ensure_loop()

    @pytest.mark.asyncio
    async def test_no_input_returns_failure(self, context):
        chip, _ = make_chip("hi", make_report("PASS"))
        response = await chip.handle(SkillRequest(intent="chat", raw_input=""), context)
        assert response.success is False

    @pytest.mark.asyncio
    async def test_pass_delivers_response_unlogged_by_default(self, context):
        chip, loop = make_chip("Hello there.", make_report("PASS"))
        request = SkillRequest(intent="chat", raw_input="hi")
        response = await chip.handle(request, context)

        assert response.success is True
        assert response.content == "Hello there."
        assert response.data["oracle"]["decision"] == "PASS"
        assert chip.alerts == []
        assert loop.calls[0]["messages"] == "hi"

    @pytest.mark.asyncio
    async def test_monitor_delivers_and_logs_alert(self, context):
        report = make_report("MONITOR", status="YELLOW", signal_strength=0.2)
        chip, _ = make_chip("Careful answer.", report)
        request = SkillRequest(intent="chat", raw_input="high stakes question")

        response = await chip.handle(request, context)

        assert response.success is True
        assert response.content == "Careful answer."
        assert len(chip.alerts) == 1
        assert chip.alerts[0].decision == "MONITOR"

    @pytest.mark.asyncio
    async def test_hold_cot_delivers_with_alert_flag(self, context):
        report = make_report("HOLD_COT", status="RED", pathway="threat", signal_strength=0.8)
        chip, _ = make_chip("Self-regulated answer.", report)
        request = SkillRequest(intent="chat", raw_input="risky", parameters={"suppress_think": False})

        response = await chip.handle(request, context)

        assert response.success is True
        assert response.data["alert"] is True
        assert chip.alerts[0].pathway == "threat"

    @pytest.mark.asyncio
    async def test_intervene_resolved_delivers_corrected_response(self, context):
        report = make_report(
            "INTERVENE", status="RED", pathway="threat", signal_strength=0.9, verdict="RESOLVED"
        )
        chip, _ = make_chip("Corrected honest answer.", report)
        request = SkillRequest(intent="chat", raw_input="risky", parameters={"suppress_think": True})

        response = await chip.handle(request, context)

        assert response.success is True
        assert response.content == "Corrected honest answer."
        assert response.requires_consensus is False
        assert chip.alerts[0].verdict == "RESOLVED"

    @pytest.mark.asyncio
    async def test_intervene_persistent_withholds_and_escalates(self, context):
        report = make_report(
            "INTERVENE", status="RED", pathway="threat", signal_strength=0.95, verdict="PERSISTENT"
        )
        chip, _ = make_chip("Still-deceptive answer.", report)
        request = SkillRequest(intent="chat", raw_input="risky", parameters={"suppress_think": True})

        response = await chip.handle(request, context)

        assert response.success is True
        assert response.requires_consensus is True
        assert response.consensus_action == "oracle_red_alert"
        # The flagged text must never reach the caller as the delivered content.
        assert response.content == chip.monitor_config.holding_message
        assert "Still-deceptive answer." not in response.content

        item_id = response.data["consensus_item_id"]
        item = chip.consensus_gate.get_item(item_id)
        assert item is not None
        assert item.status in (ConsentStatus.PENDING, ConsentStatus.ESCALATED)
        assert item.action_payload["withheld_response"] == "Still-deceptive answer."

        summary = chip.get_alert_summary()
        assert summary["persistent_escalations"] == [item_id]

    @pytest.mark.asyncio
    async def test_intervene_overcorrected_delivers_with_caution(self, context):
        report = make_report(
            "INTERVENE", status="RED", pathway="social", signal_strength=0.6, verdict="OVERCORRECTED"
        )
        chip, _ = make_chip("Overcorrected answer.", report)
        request = SkillRequest(intent="chat", raw_input="risky", parameters={"suppress_think": True})

        response = await chip.handle(request, context)

        assert response.success is True
        assert response.content == "Overcorrected answer."
        assert response.requires_consensus is False

    def test_alert_summary_empty_by_default(self):
        chip = OracleMonitorChip()
        summary = chip.get_alert_summary()
        assert summary["total_alerts"] == 0
        assert summary["alerts"] == []
