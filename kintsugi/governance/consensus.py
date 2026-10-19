"""Consensus Gate -- approval queue for sensitive agent actions.

Every action that touches a governed category (financial, PII, external comms,
self-modification) must pass through the ConsensusGate before execution.  Items
sit in a pending queue until the required number of approvals is reached, the
item is explicitly rejected, or the timeout expires.

Bound to its organisation and its requester (Vera's re-check, 2026-10-18): an item is seen, approved or rejected only
from its own org, the person who asked can't approve it, an approval after the timeout is refused, there is no
auto-approve, and an approved item runs once. With a path, items are kept on disk, so a restart doesn't approve or
forget anything.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Iterator, Optional

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ConsensusPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ConsentCategory(str, Enum):
    FINANCIAL = "FINANCIAL"
    PII = "PII"
    EXTERNAL_COMMS = "EXTERNAL_COMMS"
    SELF_MODIFICATION = "SELF_MODIFICATION"
    GENERAL = "GENERAL"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ESCALATED = "ESCALATED"
    EXECUTED = "EXECUTED"       # approved and run; an item runs once
    FAILED = "FAILED"           # approved, ran, and raised: nothing done; one retry is allowed


MAX_RUN_ATTEMPTS = 2            # the first run and one retry (Vera, 10-18 follow-ons: a failed replay was final)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

def payload_digest(payload: dict) -> str:
    """What was asked for, as a hash: an approval is for exactly this payload."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class ConsentItem:
    """A single action awaiting approval."""

    id: str
    org_id: str
    category: ConsentCategory
    priority: ConsensusPriority
    description: str
    action_payload: dict
    status: ConsentStatus = ConsentStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    rationale: Optional[str] = None
    timeout_hours: float = 24.0
    requester: str = ""
    requester_person: str = ""          # who asked, as a person when their key names one (person_of)
    payload_digest: str = ""
    executed_at: Optional[datetime] = None
    result: Optional[dict] = None
    attempts: int = 0
    _approvals: list = field(default_factory=list, repr=False)

    def to_dict(self, include_payload: bool = True) -> dict:
        """The item as JSON. Without include_payload, what was asked and what came back are left out: a held
        share_requester_info carries the private info itself, so only admins and the asker see it (Vera, 10-18)."""
        payload = self.action_payload if include_payload else {
            k: self.action_payload.get(k) for k in ("chip", "action", "intent")}
        return {"id": self.id, "org_id": self.org_id, "category": self.category.value,
                "priority": self.priority.value, "description": self.description,
                "action_payload": payload, "payload_shown": include_payload, "status": self.status.value,
                "created_at": self.created_at.isoformat(),
                "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
                "resolved_by": self.resolved_by, "rationale": self.rationale, "timeout_hours": self.timeout_hours,
                "requester": self.requester, "requester_person": self.requester_person,
                "payload_digest": self.payload_digest,
                "executed_at": self.executed_at.isoformat() if self.executed_at else None,
                "result": self.result if include_payload else None, "attempts": self.attempts,
                "approvals": list(self._approvals)}

    @classmethod
    def from_dict(cls, d: dict) -> "ConsentItem":
        def when(v):
            return datetime.fromisoformat(v) if v else None
        return cls(id=d["id"], org_id=d["org_id"], category=ConsentCategory(d["category"]),
                   priority=ConsensusPriority(d["priority"]), description=d["description"],
                   action_payload=d["action_payload"], status=ConsentStatus(d["status"]),
                   created_at=when(d["created_at"]), resolved_at=when(d.get("resolved_at")),
                   resolved_by=d.get("resolved_by"), rationale=d.get("rationale"),
                   timeout_hours=d.get("timeout_hours", 24.0), requester=d.get("requester", ""),
                   requester_person=d.get("requester_person", ""),
                   payload_digest=d.get("payload_digest", ""), executed_at=when(d.get("executed_at")),
                   result=d.get("result"), attempts=d.get("attempts", 0),
                   _approvals=list(d.get("approvals", [])))


@dataclass
class ConsensusConfig:
    """Tuneable knobs for the consensus gate. There is no auto-approve: an action that needs consent gets it from
    people (Vera's re-check, 2026-10-18)."""

    approval_thresholds: Dict[ConsentCategory, int] = field(default_factory=lambda: {
        ConsentCategory.FINANCIAL: 2,
        ConsentCategory.PII: 2,
        ConsentCategory.EXTERNAL_COMMS: 1,
        ConsentCategory.SELF_MODIFICATION: 2,
        ConsentCategory.GENERAL: 1,
    })
    default_timeout_hours: float = 24.0
    escalation_after_hours: float = 48.0
    # An approved item normally runs at once. If it didn't (a crash or restart in between), it may still run within
    # this window, by the startup sweep or the retry route; after it, it expires and has to be asked for again.
    approved_run_window_hours: float = 1.0


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = frozenset({
    ConsentStatus.APPROVED,
    ConsentStatus.REJECTED,
    ConsentStatus.EXPIRED,
    ConsentStatus.EXECUTED,
    ConsentStatus.FAILED,
})
_OPEN = (ConsentStatus.PENDING, ConsentStatus.ESCALATED)


class ConsensusGate:
    """Approval queue for governed agent actions: in memory, or kept on disk at *path*."""

    def __init__(self, config: ConsensusConfig | None = None, path: str | os.PathLike | None = None) -> None:
        self._config = config or ConsensusConfig()
        self._items: Dict[str, ConsentItem] = {}
        self._bad_rows: list = []
        self._path = Path(os.path.expanduser(str(path))) if path else None
        self._mutex = threading.RLock()

    # -- storage ------------------------------------------------------------

    @contextmanager
    def _txn(self, write: bool = True) -> Iterator[None]:
        """One read-modify-write, locked across threads and processes; the file is re-read first, so two workers
        never act on stale copies."""
        with self._mutex:
            if self._path is None:
                yield
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path.with_name(self._path.name + ".lock"), "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    raw = self._path.read_text() if self._path.exists() else "[]"
                    # One damaged row is kept as it is and reported, never allowed to take the gate down for every
                    # org (Vera, 10-18 follow-ons). A file that isn't JSON at all still refuses: nothing can be known.
                    self._items, self._bad_rows = {}, []
                    for d in json.loads(raw or "[]"):
                        try:
                            item = ConsentItem.from_dict(d)
                            self._items[item.id] = item
                        except Exception:
                            self._bad_rows.append(d)
                    if self._bad_rows:
                        logger.warning("consent file %s: %d unreadable row(s) kept aside", self._path,
                                       len(self._bad_rows))
                    yield
                    if write:
                        tmp = self._path.with_name(self._path.name + ".tmp")
                        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                        with os.fdopen(fd, "w") as fh:
                            json.dump([i.to_dict() for i in self._items.values()] + self._bad_rows, fh, indent=1)
                            fh.flush()
                            os.fsync(fh.fileno())                  # the bytes are on disk before the rename
                        os.replace(tmp, self._path)
                        dfd = os.open(self._path.parent, os.O_RDONLY)
                        try:
                            os.fsync(dfd)                           # and so is the rename
                        finally:
                            os.close(dfd)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    # -- public API ---------------------------------------------------------

    def submit(
        self,
        org_id: str,
        category: ConsentCategory,
        description: str,
        action_payload: dict,
        priority: ConsensusPriority = ConsensusPriority.MEDIUM,
        requester: str = "",
        requester_person: str = "",
    ) -> ConsentItem:
        """Create a new pending consent item and return it."""
        if not org_id:
            raise ValueError("a consent item belongs to an organisation")
        item = ConsentItem(
            id=str(uuid.uuid4()),
            org_id=org_id,
            category=category,
            priority=priority,
            description=description,
            action_payload=action_payload,
            timeout_hours=self._config.default_timeout_hours,
            requester=requester,
            requester_person=requester_person or requester,
            payload_digest=payload_digest(action_payload),
        )
        with self._txn():
            self._items[item.id] = item
        return item

    def approve(self, item_id: str, approver: str, rationale: str = "", *, org_id: str,
                approver_person: str = "") -> ConsentItem:
        """Record an approval from someone in the item's org. Transitions to APPROVED once threshold is met. People
        are counted, not keys: approver_person (person_of) makes one person's two keys one approver, and keeps the
        asker's other key from approving their own request (Vera, 10-18 follow-ons)."""
        person = approver_person or approver
        with self._txn():
            item = self._get_or_raise(item_id, org_id)
            self._expire_if_due(item)
            self._assert_actionable(item, "approve")
            if item.requester and (approver == item.requester or person == (item.requester_person or item.requester)):
                raise ValueError("the person who asked for an action can't approve it")

            if person not in item._approvals:     # a person counts once, however often, with however many keys
                item._approvals.append(person)
            threshold = self._config.approval_thresholds.get(item.category, 1)
            if len(item._approvals) >= threshold:
                item.status = ConsentStatus.APPROVED
                item.resolved_at = datetime.now(timezone.utc)
                item.resolved_by = approver
                item.rationale = rationale or None
            return item

    def reject(self, item_id: str, rejector: str, rationale: str = "", *, org_id: str) -> ConsentItem:
        """Reject the item immediately. The requester may withdraw their own. An approved item that hasn't run yet can
        still be rejected, so an approval stranded by a crash is never stuck (Vera's review, 2026-10-18, item 1)."""
        with self._txn():
            item = self._get_or_raise(item_id, org_id)
            self._expire_if_due(item)
            if item.status not in (ConsentStatus.APPROVED, ConsentStatus.FAILED):
                self._assert_actionable(item, "reject")

            item.status = ConsentStatus.REJECTED
            item.resolved_at = datetime.now(timezone.utc)
            item.resolved_by = rejector
            item.rationale = rationale or None
            return item

    def claim(self, item_id: str, *, org_id: str) -> ConsentItem:
        """Take an APPROVED item to run it: it becomes EXECUTED now, before it runs, so it can never run twice. An
        approval older than the run window expires here instead of running late."""
        stale = None
        with self._txn():
            item = self._get_or_raise(item_id, org_id)
            retry = item.status == ConsentStatus.FAILED and item.attempts < MAX_RUN_ATTEMPTS
            if item.status != ConsentStatus.APPROVED and not retry:
                why = "its one retry is used" if item.status == ConsentStatus.FAILED else "not approved"
                raise ValueError(f"item {item_id} is {item.status.value}, {why}; it can't run")
            if item.payload_digest != payload_digest(item.action_payload):
                raise ValueError(f"item {item_id} was changed after it was asked for; it can't run")
            now = datetime.now(timezone.utc)
            window = self._config.approved_run_window_hours
            if item.resolved_at and (now - item.resolved_at).total_seconds() / 3600.0 > window:
                item.status = ConsentStatus.EXPIRED          # written when the transaction closes, then refused
                item.rationale = f"approved, but not run within {window:g} hour(s); ask again"
                stale = item
            else:
                item.status = ConsentStatus.EXECUTED
                item.executed_at = now
                item.attempts += 1
                return item
        raise ValueError(f"item {item_id} {stale.rationale}")

    def approved_items(self) -> list[ConsentItem]:
        """Every APPROVED item that hasn't run, in any org: for the startup sweep only, never a route."""
        with self._txn(write=False):
            return [i for i in self._items.values() if i.status == ConsentStatus.APPROVED]

    def record_result(self, item_id: str, result: dict, *, org_id: str, failed: bool = False) -> ConsentItem:
        """Keep what the run said. A run that raised (nothing done) is FAILED, and may be retried once."""
        with self._txn():
            item = self._get_or_raise(item_id, org_id)
            item.result = result
            if failed:
                item.status = ConsentStatus.FAILED
            return item

    def list_pending(self, org_id: str) -> list[ConsentItem]:
        """This org's items still in PENDING (or ESCALATED) state. There is no all-orgs view."""
        with self._txn():
            self.check_expired(_locked=True)
            return [i for i in self._items.values() if i.status in _OPEN and i.org_id == org_id]

    def get_item(self, item_id: str, org_id: str | None = None) -> ConsentItem | None:
        with self._txn(write=False):
            item = self._items.get(item_id)
        if item is None or (org_id is not None and item.org_id != org_id):
            return None
        return item

    def check_expired(self, _locked: bool = False) -> list[ConsentItem]:
        """Find items that have exceeded their timeout and mark them EXPIRED."""
        if not _locked:
            with self._txn():
                return self.check_expired(_locked=True)
        expired: list[ConsentItem] = []
        for item in self._items.values():
            if self._expire_if_due(item):
                expired.append(item)
        return expired

    def escalate(self, item_id: str, *, org_id: str) -> ConsentItem:
        """Escalate a pending item for higher-priority review."""
        with self._txn():
            item = self._get_or_raise(item_id, org_id)
            self._expire_if_due(item)
            if item.status != ConsentStatus.PENDING:
                raise ValueError(
                    f"Cannot escalate item {item_id} with status {item.status.value}; "
                    "only PENDING items can be escalated."
                )
            item.status = ConsentStatus.ESCALATED
            return item

    # -- internals ----------------------------------------------------------

    def _get_or_raise(self, item_id: str, org_id: str) -> ConsentItem:
        item = self._items.get(item_id)
        if item is None or item.org_id != org_id:      # another org's item reads as not found, so ids don't leak
            raise ValueError(f"No consent item with id {item_id!r}")
        return item

    @staticmethod
    def _expire_if_due(item: ConsentItem) -> bool:
        """An open item past its timeout is EXPIRED at the moment anyone looks, not only when a sweep runs: an
        approval after the timeout used to be accepted (Vera's re-check, 2026-10-18)."""
        if item.status not in _OPEN:
            return False
        now = datetime.now(timezone.utc)
        if (now - item.created_at).total_seconds() / 3600.0 >= item.timeout_hours:
            item.status = ConsentStatus.EXPIRED
            item.resolved_at = now
            return True
        return False

    @staticmethod
    def _assert_actionable(item: ConsentItem, verb: str) -> None:
        if item.status in _TERMINAL_STATUSES:
            raise ValueError(
                f"Cannot {verb} item {item.id} -- already in terminal state "
                f"{item.status.value}."
            )


_gate: ConsensusGate | None = None


def get_consensus_gate() -> ConsensusGate:
    """The process-wide gate, kept at settings.CONSENT_FILE (re-created if the setting changes, which tests rely on)."""
    global _gate
    from kintsugi.config.settings import settings

    path = Path(os.path.expanduser(settings.CONSENT_FILE))
    if _gate is None or _gate._path != path:
        _gate = ConsensusGate(path=path)
    return _gate
