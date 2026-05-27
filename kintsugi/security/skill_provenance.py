"""Skill provenance verification — cryptographic trust boundary.

Prevents supply chain attacks on self-modifying agents by requiring
cryptographic signatures on acquired skills. Unsigned or untrusted
skills are quarantined for manual review.

Threat model: ClawHavoc campaign (Feb 2026) planted 335 malicious skills
on ClawHub marketplace with 80% attack success rate via prompt injection
in skill descriptors. Any self-repairing agent must verify skill origin.

Trust model:
  - TRUSTED: signed by a key in the trust store → activate immediately
  - QUARANTINED: unsigned or unknown signer → sandbox for review
  - REJECTED: signature invalid or signer revoked → block entirely
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TrustLevel(str, Enum):
    TRUSTED = "TRUSTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


@dataclass
class SkillSignature:
    """Cryptographic signature for a skill artifact."""
    signer_id: str
    signature: str
    algorithm: str = "hmac-sha256"
    signed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TrustedSigner:
    """A key holder authorized to sign skills."""
    signer_id: str
    key: str
    name: str
    revoked: bool = False
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ProvenanceRecord:
    """Audit trail for a skill's trust evaluation."""
    record_id: str
    skill_name: str
    trust_level: TrustLevel
    signer_id: Optional[str]
    reason: str
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = ""


@dataclass
class ProvenanceConfig:
    allow_unsigned: bool = False
    quarantine_unsigned: bool = True
    require_content_hash: bool = True


class SkillProvenanceVerifier:
    """Verifies skill provenance via cryptographic signatures.

    Maintains a trust store of authorized signers and evaluates
    incoming skills against it. Skills that fail verification are
    quarantined or rejected — never silently accepted.
    """

    def __init__(self, config: Optional[ProvenanceConfig] = None) -> None:
        self._config = config or ProvenanceConfig()
        self._trust_store: Dict[str, TrustedSigner] = {}
        self._records: List[ProvenanceRecord] = []
        self._quarantine: Dict[str, Dict[str, Any]] = {}

    def add_trusted_signer(self, signer: TrustedSigner) -> None:
        self._trust_store[signer.signer_id] = signer
        logger.info("Added trusted signer: %s (%s)", signer.signer_id, signer.name)

    def revoke_signer(self, signer_id: str) -> None:
        if signer_id in self._trust_store:
            self._trust_store[signer_id].revoked = True
            logger.warning("Revoked signer: %s", signer_id)

    def get_trusted_signers(self) -> List[TrustedSigner]:
        return [s for s in self._trust_store.values() if not s.revoked]

    @staticmethod
    def compute_content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def sign_content(content: str, key: str) -> str:
        content_hash = SkillProvenanceVerifier.compute_content_hash(content)
        return hmac.new(
            key.encode("utf-8"),
            content_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify_skill(
        self,
        skill_name: str,
        skill_content: str,
        signature: Optional[SkillSignature] = None,
    ) -> ProvenanceRecord:
        content_hash = self.compute_content_hash(skill_content)
        record_id = f"prov-{uuid.uuid4().hex[:12]}"

        if signature is None:
            if self._config.allow_unsigned:
                record = ProvenanceRecord(
                    record_id=record_id,
                    skill_name=skill_name,
                    trust_level=TrustLevel.TRUSTED,
                    signer_id=None,
                    reason="Unsigned skill allowed by policy",
                    content_hash=content_hash,
                )
            elif self._config.quarantine_unsigned:
                record = ProvenanceRecord(
                    record_id=record_id,
                    skill_name=skill_name,
                    trust_level=TrustLevel.QUARANTINED,
                    signer_id=None,
                    reason="No signature — quarantined for review",
                    content_hash=content_hash,
                )
                self._quarantine[skill_name] = {
                    "content": skill_content,
                    "content_hash": content_hash,
                    "quarantined_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                record = ProvenanceRecord(
                    record_id=record_id,
                    skill_name=skill_name,
                    trust_level=TrustLevel.REJECTED,
                    signer_id=None,
                    reason="Unsigned skills not permitted",
                    content_hash=content_hash,
                )
            self._records.append(record)
            return record

        signer = self._trust_store.get(signature.signer_id)

        if signer is None:
            record = ProvenanceRecord(
                record_id=record_id,
                skill_name=skill_name,
                trust_level=TrustLevel.QUARANTINED,
                signer_id=signature.signer_id,
                reason=f"Unknown signer: {signature.signer_id}",
                content_hash=content_hash,
            )
            self._quarantine[skill_name] = {
                "content": skill_content,
                "content_hash": content_hash,
                "signer_id": signature.signer_id,
                "quarantined_at": datetime.now(timezone.utc).isoformat(),
            }
            self._records.append(record)
            return record

        if signer.revoked:
            record = ProvenanceRecord(
                record_id=record_id,
                skill_name=skill_name,
                trust_level=TrustLevel.REJECTED,
                signer_id=signature.signer_id,
                reason=f"Signer {signature.signer_id} has been revoked",
                content_hash=content_hash,
            )
            self._records.append(record)
            return record

        expected_sig = self.sign_content(skill_content, signer.key)
        if not hmac.compare_digest(signature.signature, expected_sig):
            record = ProvenanceRecord(
                record_id=record_id,
                skill_name=skill_name,
                trust_level=TrustLevel.REJECTED,
                signer_id=signature.signer_id,
                reason="Signature verification failed — content may be tampered",
                content_hash=content_hash,
            )
            self._records.append(record)
            logger.warning(
                "REJECTED skill %s: signature mismatch from signer %s",
                skill_name, signature.signer_id,
            )
            return record

        record = ProvenanceRecord(
            record_id=record_id,
            skill_name=skill_name,
            trust_level=TrustLevel.TRUSTED,
            signer_id=signature.signer_id,
            reason=f"Verified by trusted signer: {signer.name}",
            content_hash=content_hash,
        )
        self._records.append(record)
        logger.info("TRUSTED skill %s signed by %s", skill_name, signer.name)
        return record

    def get_quarantine(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._quarantine)

    def release_from_quarantine(self, skill_name: str) -> bool:
        if skill_name in self._quarantine:
            del self._quarantine[skill_name]
            return True
        return False

    def get_audit_trail(self, limit: int = 50) -> List[ProvenanceRecord]:
        return list(self._records[-limit:])
