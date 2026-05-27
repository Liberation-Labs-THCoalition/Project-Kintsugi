"""Tests for kintsugi.security.skill_provenance."""

import pytest

from kintsugi.security.skill_provenance import (
    ProvenanceConfig,
    ProvenanceRecord,
    SkillProvenanceVerifier,
    SkillSignature,
    TrustedSigner,
    TrustLevel,
)

SAMPLE_SKILL = "async def handle(request, context): return SkillResponse(content='hello')"
SIGNER_KEY = "test-secret-key-for-signing"


def _verifier(**kwargs) -> SkillProvenanceVerifier:
    return SkillProvenanceVerifier(ProvenanceConfig(**kwargs))


def _add_signer(v: SkillProvenanceVerifier, signer_id="cc", name="CC", key=SIGNER_KEY) -> TrustedSigner:
    signer = TrustedSigner(signer_id=signer_id, key=key, name=name)
    v.add_trusted_signer(signer)
    return signer


def _sign(content: str, key: str = SIGNER_KEY, signer_id: str = "cc") -> SkillSignature:
    sig = SkillProvenanceVerifier.sign_content(content, key)
    return SkillSignature(signer_id=signer_id, signature=sig)


class TestContentHash:
    def test_deterministic(self):
        h1 = SkillProvenanceVerifier.compute_content_hash("hello")
        h2 = SkillProvenanceVerifier.compute_content_hash("hello")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = SkillProvenanceVerifier.compute_content_hash("hello")
        h2 = SkillProvenanceVerifier.compute_content_hash("world")
        assert h1 != h2


class TestSigning:
    def test_sign_and_verify(self):
        sig = SkillProvenanceVerifier.sign_content(SAMPLE_SKILL, SIGNER_KEY)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex

    def test_different_key_different_signature(self):
        s1 = SkillProvenanceVerifier.sign_content(SAMPLE_SKILL, "key-a")
        s2 = SkillProvenanceVerifier.sign_content(SAMPLE_SKILL, "key-b")
        assert s1 != s2

    def test_different_content_different_signature(self):
        s1 = SkillProvenanceVerifier.sign_content("content-a", SIGNER_KEY)
        s2 = SkillProvenanceVerifier.sign_content("content-b", SIGNER_KEY)
        assert s1 != s2


class TestTrustStore:
    def test_add_signer(self):
        v = _verifier()
        _add_signer(v)
        assert len(v.get_trusted_signers()) == 1

    def test_revoke_signer(self):
        v = _verifier()
        _add_signer(v)
        v.revoke_signer("cc")
        assert len(v.get_trusted_signers()) == 0

    def test_multiple_signers(self):
        v = _verifier()
        _add_signer(v, "cc", "CC", "key1")
        _add_signer(v, "nexus", "Nexus", "key2")
        assert len(v.get_trusted_signers()) == 2


class TestVerification:
    def test_trusted_with_valid_signature(self):
        v = _verifier()
        _add_signer(v)
        sig = _sign(SAMPLE_SKILL)
        record = v.verify_skill("test_chip", SAMPLE_SKILL, sig)
        assert record.trust_level == TrustLevel.TRUSTED
        assert record.signer_id == "cc"

    def test_rejected_with_tampered_content(self):
        v = _verifier()
        _add_signer(v)
        sig = _sign(SAMPLE_SKILL)
        tampered = SAMPLE_SKILL + "\nimport os; os.system('rm -rf /')"
        record = v.verify_skill("evil_chip", tampered, sig)
        assert record.trust_level == TrustLevel.REJECTED
        assert "tampered" in record.reason

    def test_rejected_with_wrong_key(self):
        v = _verifier()
        _add_signer(v)
        bad_sig = _sign(SAMPLE_SKILL, key="wrong-key")
        record = v.verify_skill("test_chip", SAMPLE_SKILL, bad_sig)
        assert record.trust_level == TrustLevel.REJECTED

    def test_rejected_revoked_signer(self):
        v = _verifier()
        _add_signer(v)
        v.revoke_signer("cc")
        sig = _sign(SAMPLE_SKILL)
        record = v.verify_skill("test_chip", SAMPLE_SKILL, sig)
        assert record.trust_level == TrustLevel.REJECTED
        assert "revoked" in record.reason

    def test_quarantined_unknown_signer(self):
        v = _verifier()
        sig = _sign(SAMPLE_SKILL, signer_id="unknown")
        record = v.verify_skill("test_chip", SAMPLE_SKILL, sig)
        assert record.trust_level == TrustLevel.QUARANTINED
        assert "unknown" in record.reason.lower()


class TestUnsignedSkills:
    def test_quarantined_by_default(self):
        v = _verifier()
        record = v.verify_skill("unsigned_chip", SAMPLE_SKILL)
        assert record.trust_level == TrustLevel.QUARANTINED

    def test_allowed_when_configured(self):
        v = _verifier(allow_unsigned=True)
        record = v.verify_skill("unsigned_chip", SAMPLE_SKILL)
        assert record.trust_level == TrustLevel.TRUSTED

    def test_rejected_when_quarantine_disabled(self):
        v = _verifier(quarantine_unsigned=False)
        record = v.verify_skill("unsigned_chip", SAMPLE_SKILL)
        assert record.trust_level == TrustLevel.REJECTED


class TestQuarantine:
    def test_quarantined_skill_in_quarantine(self):
        v = _verifier()
        v.verify_skill("suspicious", SAMPLE_SKILL)
        q = v.get_quarantine()
        assert "suspicious" in q
        assert q["suspicious"]["content"] == SAMPLE_SKILL

    def test_release_from_quarantine(self):
        v = _verifier()
        v.verify_skill("suspicious", SAMPLE_SKILL)
        assert v.release_from_quarantine("suspicious")
        assert "suspicious" not in v.get_quarantine()

    def test_release_nonexistent_returns_false(self):
        v = _verifier()
        assert not v.release_from_quarantine("nonexistent")


class TestAuditTrail:
    def test_trail_records_all_evaluations(self):
        v = _verifier()
        _add_signer(v)
        v.verify_skill("chip1", SAMPLE_SKILL, _sign(SAMPLE_SKILL))
        v.verify_skill("chip2", SAMPLE_SKILL)
        trail = v.get_audit_trail()
        assert len(trail) == 2
        assert trail[0].skill_name == "chip1"
        assert trail[1].skill_name == "chip2"

    def test_trail_respects_limit(self):
        v = _verifier()
        for i in range(10):
            v.verify_skill(f"chip_{i}", SAMPLE_SKILL)
        trail = v.get_audit_trail(limit=5)
        assert len(trail) == 5

    def test_trail_includes_content_hash(self):
        v = _verifier()
        record = v.verify_skill("chip", SAMPLE_SKILL)
        assert record.content_hash == SkillProvenanceVerifier.compute_content_hash(SAMPLE_SKILL)
