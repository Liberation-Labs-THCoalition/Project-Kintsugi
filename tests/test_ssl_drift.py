"""Tests for SSL drift decomposition (Scheduling/Structural/Logical)."""

from datetime import datetime, timezone, timedelta

import pytest

from kintsugi.kintsugi_engine.drift import (
    DriftConfig,
    DriftDetector,
    DriftLayer,
    SSLDriftProfile,
    SSLDriftSignal,
)


class TestSSLDriftSignal:
    def test_valid_magnitude(self):
        s = SSLDriftSignal(layer=DriftLayer.SCHEDULING, magnitude=0.5, description="test")
        assert s.magnitude == 0.5

    def test_invalid_magnitude_raises(self):
        with pytest.raises(ValueError):
            SSLDriftSignal(layer=DriftLayer.SCHEDULING, magnitude=1.5, description="bad")

    def test_zero_magnitude(self):
        s = SSLDriftSignal(layer=DriftLayer.LOGICAL, magnitude=0.0, description="none")
        assert s.magnitude == 0.0


class TestSSLDriftProfile:
    def test_dominant_layer(self):
        p = SSLDriftProfile(scheduling=0.8, structural=0.2, logical=0.1)
        assert p.dominant_layer == DriftLayer.SCHEDULING

    def test_dominant_layer_logical(self):
        p = SSLDriftProfile(scheduling=0.1, structural=0.2, logical=0.9)
        assert p.dominant_layer == DriftLayer.LOGICAL

    def test_total_drift(self):
        p = SSLDriftProfile(scheduling=0.3, structural=0.6, logical=0.9)
        assert abs(p.total_drift - 0.6) < 0.001

    def test_remediation_hint_scheduling(self):
        p = SSLDriftProfile(scheduling=0.8, structural=0.1, logical=0.1)
        assert "timing" in p.get_remediation_hint().lower()

    def test_remediation_hint_structural(self):
        p = SSLDriftProfile(scheduling=0.1, structural=0.8, logical=0.1)
        assert "tool" in p.get_remediation_hint().lower()

    def test_remediation_hint_logical(self):
        p = SSLDriftProfile(scheduling=0.1, structural=0.1, logical=0.8)
        assert "reasoning" in p.get_remediation_hint().lower() or "logic" in p.get_remediation_hint().lower()


class TestSSLDriftAnalysis:
    def _detector(self):
        return DriftDetector(DriftConfig())

    def test_empty_actions_returns_zero_profile(self):
        d = self._detector()
        profile = d.analyze_ssl_drift([], {})
        assert profile.total_drift == 0.0
        assert len(profile.signals) == 0

    def test_scheduling_drift_detected(self):
        d = self._detector()
        now = datetime.now(timezone.utc)
        actions = [
            {"timestamp": (now - timedelta(hours=i*10)).isoformat()}
            for i in range(5)
        ]
        profile = d.analyze_ssl_drift(actions, {"expected_frequency_hours": 2.0})
        assert profile.scheduling > 0.3
        assert any(s.layer == DriftLayer.SCHEDULING for s in profile.signals)

    def test_no_scheduling_drift_when_on_time(self):
        d = self._detector()
        now = datetime.now(timezone.utc)
        actions = [
            {"timestamp": (now - timedelta(hours=i*2)).isoformat()}
            for i in range(5)
        ]
        profile = d.analyze_ssl_drift(actions, {"expected_frequency_hours": 2.0})
        assert profile.scheduling < 0.3

    def test_structural_drift_wrong_tools(self):
        d = self._detector()
        actions = [
            {"tools_used": ["discord_send", "unknown_api"]},
            {"tools_used": ["unknown_api"]},
        ]
        expected = {"expected_tools": ["slack_send", "email_send"]}
        profile = d.analyze_ssl_drift(actions, expected)
        assert profile.structural > 0.3
        assert any(s.layer == DriftLayer.STRUCTURAL for s in profile.signals)

    def test_no_structural_drift_correct_tools(self):
        d = self._detector()
        actions = [
            {"tools_used": ["slack_send", "email_send"]},
        ]
        expected = {"expected_tools": ["slack_send", "email_send"]}
        profile = d.analyze_ssl_drift(actions, expected)
        assert profile.structural == 0.0

    def test_logical_drift_low_quality(self):
        d = self._detector()
        actions = [
            {"output_quality": 0.3},
            {"output_quality": 0.4},
            {"output_quality": 0.2},
        ]
        expected = {"min_output_quality": 0.7}
        profile = d.analyze_ssl_drift(actions, expected)
        assert profile.logical > 0.3
        assert any(s.layer == DriftLayer.LOGICAL for s in profile.signals)

    def test_no_logical_drift_good_quality(self):
        d = self._detector()
        actions = [
            {"output_quality": 0.9},
            {"output_quality": 0.85},
        ]
        expected = {"min_output_quality": 0.7}
        profile = d.analyze_ssl_drift(actions, expected)
        assert profile.logical == 0.0

    def test_combined_drift(self):
        d = self._detector()
        now = datetime.now(timezone.utc)
        actions = [
            {
                "timestamp": (now - timedelta(hours=i*8)).isoformat(),
                "tools_used": ["wrong_tool"],
                "output_quality": 0.3,
            }
            for i in range(5)
        ]
        expected = {
            "expected_frequency_hours": 2.0,
            "expected_tools": ["right_tool"],
            "min_output_quality": 0.7,
        }
        profile = d.analyze_ssl_drift(actions, expected)
        assert profile.scheduling > 0
        assert profile.structural > 0
        assert profile.logical > 0
        assert len(profile.signals) == 3

    def test_datetime_objects_accepted(self):
        d = self._detector()
        now = datetime.now(timezone.utc)
        actions = [
            {"timestamp": now - timedelta(hours=i*2)}
            for i in range(3)
        ]
        profile = d.analyze_ssl_drift(actions, {"expected_frequency_hours": 2.0})
        assert isinstance(profile, SSLDriftProfile)
