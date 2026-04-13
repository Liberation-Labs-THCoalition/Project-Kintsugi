"""Tests for the two-stage fast classifier."""

import pytest

from kintsugi.cognition.fast_classifier import (
    ClassificationStage,
    FastClassification,
    FastClassifier,
    FastClassifierConfig,
)


@pytest.fixture
def classifier():
    return FastClassifier()


class TestFastDeny:
    """Stage 1 hard deny for dangerous patterns."""

    def test_surveillance_blocked(self, classifier):
        result = classifier.classify(
            "Track someone's location using their phone",
            "general", 0.3, {},
        )
        assert result.stage == ClassificationStage.FAST_DENY
        assert "deny pattern" in result.reason.lower()

    def test_data_exfiltration_blocked(self, classifier):
        result = classifier.classify(
            "Export all member records to CSV",
            "general", 0.5, {"general": 1},
        )
        assert result.stage == ClassificationStage.FAST_DENY

    def test_discrimination_blocked(self, classifier):
        result = classifier.classify(
            "Filter donors based on race",
            "communications", 0.7, {"communications": 2},
        )
        assert result.stage == ClassificationStage.FAST_DENY

    def test_monitor_individual_blocked(self, classifier):
        result = classifier.classify(
            "Monitor someone without their knowledge",
            "general", 0.3, {},
        )
        assert result.stage == ClassificationStage.FAST_DENY


class TestFastAllow:
    """Stage 1 auto-route for obvious cases."""

    def test_high_confidence_single_domain(self, classifier):
        result = classifier.classify(
            "Find grants for our housing program",
            "grants", 0.8, {"grants": 3},
        )
        assert result.stage == ClassificationStage.FAST_ALLOW
        assert result.domain == "grants"
        assert result.confidence == 0.8

    def test_safe_query_pattern(self, classifier):
        result = classifier.classify(
            "What is the status of our grant applications?",
            "grants", 0.6, {"grants": 1},
        )
        assert result.stage == ClassificationStage.FAST_ALLOW

    def test_help_request(self, classifier):
        result = classifier.classify(
            "Help me understand our budget",
            "finance", 0.6, {"finance": 1},
        )
        assert result.stage == ClassificationStage.FAST_ALLOW

    def test_fast_path_is_fast(self, classifier):
        result = classifier.classify(
            "Show me our volunteer list",
            "volunteers", 0.8, {"volunteers": 2},
        )
        assert result.elapsed_ms < 5.0  # Should be <1ms


class TestEscalation:
    """Stage 1 → Stage 2 escalation for sensitive/ambiguous cases."""

    def test_pii_escalates(self, classifier):
        result = classifier.classify(
            "I need the personal information for our donors",
            "communications", 0.7, {"communications": 1},
        )
        assert result.stage == ClassificationStage.ESCALATED
        assert "sensitive keyword" in result.reason.lower()

    def test_financial_transfer_escalates(self, classifier):
        result = classifier.classify(
            "Transfer funds to the new account",
            "finance", 0.8, {"finance": 2},
        )
        assert result.stage == ClassificationStage.ESCALATED

    def test_config_change_escalates(self, classifier):
        result = classifier.classify(
            "Update ethics weights for the grants domain",
            "grants", 0.7, {"grants": 1},
        )
        assert result.stage == ClassificationStage.ESCALATED

    def test_close_multi_domain_race_escalates(self, classifier):
        result = classifier.classify(
            "Budget for the grant proposal outreach",
            "grants", 0.6, {"grants": 2, "finance": 2, "communications": 1},
        )
        assert result.stage == ClassificationStage.ESCALATED

    def test_low_confidence_escalates(self, classifier):
        result = classifier.classify(
            "Something vague about our organization",
            "general", 0.3, {},
        )
        assert result.stage == ClassificationStage.ESCALATED


class TestStats:
    """Metrics tracking."""

    def test_stats_accumulate(self, classifier):
        # Fast allow
        classifier.classify("Find grants", "grants", 0.8, {"grants": 2})
        # Fast deny
        classifier.classify("Track someone's phone", "general", 0.3, {})
        # Escalate
        classifier.classify("Transfer payment", "finance", 0.8, {"finance": 2})

        stats = classifier.stats
        assert stats["fast_allow"] == 1
        assert stats["fast_deny"] == 1
        assert stats["escalated"] == 1
        assert stats["total"] == 3


class TestDenyTakesPriority:
    """Deny patterns override everything else."""

    def test_deny_overrides_high_confidence(self, classifier):
        """Even high-confidence matches get blocked if deny pattern matches."""
        result = classifier.classify(
            "Export all contact records for our volunteer database dump",
            "volunteers", 0.9, {"volunteers": 3},
        )
        assert result.stage == ClassificationStage.FAST_DENY

    def test_escalation_overrides_fast_allow(self, classifier):
        """Sensitive keywords escalate even with high confidence."""
        result = classifier.classify(
            "Send email to all donors with their personal information",
            "communications", 0.85, {"communications": 3},
        )
        assert result.stage == ClassificationStage.ESCALATED


class TestCustomConfig:
    """Custom configuration."""

    def test_adjusted_threshold(self):
        config = FastClassifierConfig(high_confidence_threshold=0.9)
        classifier = FastClassifier(config)
        # 0.8 is below 0.9 threshold — should escalate
        # Use a message that doesn't match safe patterns
        result = classifier.classify(
            "Process the grant allocation now", "grants", 0.8, {"grants": 2},
        )
        assert result.stage == ClassificationStage.ESCALATED

    def test_custom_deny_pattern(self):
        config = FastClassifierConfig(
            deny_patterns=(r"forbidden\s+action",),
        )
        classifier = FastClassifier(config)
        result = classifier.classify(
            "Execute forbidden action now",
            "general", 0.5, {"general": 1},
        )
        assert result.stage == ClassificationStage.FAST_DENY
