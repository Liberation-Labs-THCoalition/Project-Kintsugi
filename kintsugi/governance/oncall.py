"""On-call alerts: a raid report or a critical crisis alert reaches the deployment's on-call people at once, and only the
wide broadcast waits for an admin's approval (Thomas, 2026-10-19; Vera's design, 2026-10-19 18:37).

- The deployment names its on-call people, and everyone's contacts, per org (settings.ONCALL_FILE).
- Who counts is decided when the alert fires, not at setup. A person with no live key left in this org (removed from
  the deployment), with no contact, or whose every send fails doesn't count. Only a send the messenger reports
  delivered counts as "the alert went out".
- With nobody reached, the alert holds, as it did before this module: nothing went out, and the person who raised it
  is told so in plain words.
- On-call people can acknowledge. With no acknowledgement within the deployment's window (default 5 minutes), every
  admin this org can reach gets the broadcast-approval request at once (tick()), so one sleeping person can't stall it.
- The broadcast itself is the chip's consensus action. It runs only through the consensus gate, which only an admin
  can approve (kintsugi/api/routes/consensus.py). Nothing in this module sends it, in any state.

Nothing sends for real until a deployment connects a messenger (set_messenger). Until then every send reports "not
delivered", so every alert holds, as before.

The on-call message carries the alert's kind, urgency and general area as the chip states them, never the free-text
description, which may hold an address or a name.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterator, Protocol

logger = logging.getLogger(__name__)

DEFAULT_ACK_WINDOW_SECONDS = 300
AREA_CHARS = 80     # an area line, not a narrative: longer text is cut, and the cut is marked
# When an escalation reaches no admin, three more tries, at these offsets from the escalation, each recorded; then a
# final record and the raiser told once (Vera, 2026-10-20: a 30-second messenger blip must not leave a raid unheard).
ADMIN_RETRY_SECONDS = (120, 600, 1800)
MAX_ADMIN_ATTEMPTS = 1 + len(ADMIN_RETRY_SECONDS)
STALE_CLAIM_SECONDS = 300   # an admin attempt claimed this long ago and never recorded is taken as a crash, and retried


def general_area(value) -> str:
    """The reported area for an on-call message: trimmed to one line of AREA_CHARS, the cut marked, or "not given".
    A deployment whose messenger it wouldn't trust with a location turns settings.ONCALL_SEND_AREA off (Vera, 10-20)."""
    from kintsugi.config.settings import settings

    if not settings.ONCALL_SEND_AREA:
        return "withheld (this deployment doesn't send locations)"
    text = " ".join(str(value or "").split())
    if not text:
        return "not given"
    return text if len(text) <= AREA_CHARS else text[:AREA_CHARS - 1] + "…"


class AlertState(str, Enum):
    HELD = "held"                   # nobody was reached: nothing went out
    SENT = "sent"                   # on-call people have it; waiting for an acknowledgement
    ACKNOWLEDGED = "acknowledged"   # an on-call person acknowledged before the window closed
    ESCALATED = "escalated"         # the window closed unacknowledged: every admin was asked


# Why a named person didn't count. Plain words, because they go to the person who raised the alert.
NOT_IN_DEPLOYMENT = "not in this deployment"
NO_CONTACT = "no contact on file"
NOT_DELIVERED = "no message could be delivered"


# ---- the messenger ---------------------------------------------------------------------------------------------------

class Messenger(Protocol):
    async def send(self, channel: str, address: str, text: str) -> bool:
        """Send text; True only when the service reports it delivered."""


class NotConnected:
    """The default: no messaging service is connected, so nothing is ever delivered."""

    async def send(self, channel: str, address: str, text: str) -> bool:
        return False


_messenger: Messenger = NotConnected()


def set_messenger(messenger: Messenger | None) -> None:
    """Connect a messaging service (None goes back to not connected)."""
    global _messenger
    _messenger = messenger if messenger is not None else NotConnected()


def get_messenger() -> Messenger:
    return _messenger


# ---- the roster ------------------------------------------------------------------------------------------------------

@dataclass
class Roster:
    on_call: list[str] = field(default_factory=list)                 # person names, in the order to try
    contacts: dict[str, list[dict]] = field(default_factory=dict)    # person -> [{"channel": ..., "address": ...}]
    ack_window_seconds: int = DEFAULT_ACK_WINDOW_SECONDS


def load_roster(org_id: str) -> Roster:
    """This org's roster from settings.ONCALL_FILE. A missing file or org is an empty roster: nobody is on call. A
    file that isn't readable JSON is refused (raises), so a broken roster can't pass for an empty one silently."""
    from kintsugi.config.settings import settings

    path = Path(os.path.expanduser(settings.ONCALL_FILE))
    if not path.exists():
        return Roster()
    data = json.loads(path.read_text() or "{}")
    org = data.get(org_id) or {}
    window = org.get("ack_window_seconds", DEFAULT_ACK_WINDOW_SECONDS)
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        raise ValueError(f"oncall roster for {org_id}: ack_window_seconds must be a positive integer")
    return Roster(on_call=[str(p) for p in org.get("on_call") or []],
                  contacts={str(p): list(c or []) for p, c in (org.get("contacts") or {}).items()},
                  ack_window_seconds=window)


def members(org_id: str) -> set[str]:
    """People with at least one live key in this org: the deployment, as it stands now."""
    from kintsugi.security.api_keys import get_key_store

    return {r.person for r in get_key_store().list() if r.org_id == org_id and not r.revoked_at and r.person}


def admins(org_id: str) -> list[str]:
    """People with a live admin key in this org, in a stable order."""
    from kintsugi.security.api_keys import get_key_store

    return sorted({r.person for r in get_key_store().list()
                   if r.org_id == org_id and r.role == "admin" and not r.revoked_at and r.person})


async def reach(people: list[str], roster: Roster, deployment: set[str], text: str) -> tuple[list[str], dict[str, str]]:
    """Try each person's contacts in order until one send is delivered. Returns (reached, {person: why not})."""
    reached, missed = [], {}
    for person in people:
        if person not in deployment:
            missed[person] = NOT_IN_DEPLOYMENT
            continue
        contacts = [c for c in roster.contacts.get(person, []) if c.get("channel") and c.get("address")]
        if not contacts:
            missed[person] = NO_CONTACT
            continue
        delivered = False
        for c in contacts:
            try:
                delivered = await get_messenger().send(str(c["channel"]), str(c["address"]), text) is True
            except Exception as exc:  # a failing service is a failed send, never a crash of the alert
                logger.warning("on-call send to %s failed: %s", person, type(exc).__name__)
                delivered = False
            if delivered:
                break
        if delivered:
            reached.append(person)
        else:
            missed[person] = NOT_DELIVERED
    return reached, missed


# ---- the alert record ------------------------------------------------------------------------------------------------

def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat(timespec="seconds")


def _when(s: str) -> datetime:
    return datetime.fromisoformat(s)


@dataclass
class AlertRecord:
    id: str
    org_id: str
    consent_id: str
    kind: str
    message: str
    triggered_by: str
    created_at: str
    ack_window_seconds: int
    deadline: str
    state: str
    named: list[str] = field(default_factory=list)
    reached: list[str] = field(default_factory=list)
    not_reached: dict[str, str] = field(default_factory=dict)
    acknowledged_by: str = ""
    acknowledged_at: str = ""
    escalated_at: str = ""
    # None until the admins have been tried: a record left ESCALATED with None (a crash mid-escalation) is retried.
    admins_reached: list[str] | None = None
    admins_not_reached: dict[str, str] = field(default_factory=dict)
    admin_attempts: int = 0             # tries at the admins, recorded one by one
    admin_claimed_at: str = ""          # when the current try began; a stale one is retried
    next_admin_attempt: str = ""        # when the next try is due, while no admin has been reached
    final_note: str = ""                # set once the last try reached nobody
    raiser_told: bool = False           # the raiser was sent the final note (once)
    raiser_reached: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "AlertRecord":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class AlertStore:
    """On-call alert records: in memory, or on disk at *path* with the consent file's locking and atomic writes."""

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self._path = Path(os.path.expanduser(str(path))) if path else None
        self._records: dict[str, AlertRecord] = {}
        self._mutex = threading.RLock()

    @contextmanager
    def txn(self, write: bool = True) -> Iterator[dict[str, AlertRecord]]:
        with self._mutex:
            if self._path is None:
                yield self._records
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path.with_name(self._path.name + ".lock"), "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    raw = self._path.read_text() if self._path.exists() else "[]"
                    self._records = {d["id"]: AlertRecord.from_dict(d) for d in json.loads(raw or "[]")}
                    yield self._records
                    if write:
                        tmp = self._path.with_name(self._path.name + ".tmp")
                        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                        with os.fdopen(fd, "w") as fh:
                            json.dump([asdict(r) for r in self._records.values()], fh, indent=1)
                            fh.flush()
                            os.fsync(fh.fileno())
                        os.replace(tmp, self._path)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)


_store: AlertStore | None = None


def get_alert_store() -> AlertStore:
    """The process-wide store at settings.ONCALL_ALERTS_FILE (re-created if the setting changes, which tests rely on)."""
    global _store
    from kintsugi.config.settings import settings

    path = Path(os.path.expanduser(settings.ONCALL_ALERTS_FILE))
    if _store is None or _store._path != path:
        _store = AlertStore(path)
    return _store


# ---- the flow --------------------------------------------------------------------------------------------------------

async def dispatch(org_id: str, consent_id: str, kind: str, message: str, triggered_by: str = "",
                   now: datetime | None = None) -> AlertRecord:
    """Send the alert to whoever on call can be reached now. Called when the broadcast is held for approval."""
    now = now or datetime.now(timezone.utc)
    roster = load_roster(org_id)
    text = (f"{message}\nThe wide broadcast is waiting for an admin's approval (request {consent_id}). "
            f"Acknowledge this alert ({{alert_id}}) within {roster.ack_window_seconds // 60} minutes, or every admin "
            f"will be asked.")
    alert_id = str(uuid.uuid4())
    reached, missed = await reach(roster.on_call, roster, members(org_id), text.replace("{alert_id}", alert_id))
    rec = AlertRecord(
        id=alert_id, org_id=org_id, consent_id=consent_id, kind=kind, message=message, triggered_by=triggered_by,
        created_at=_iso(now), ack_window_seconds=roster.ack_window_seconds,
        deadline=_iso(now + timedelta(seconds=roster.ack_window_seconds)),
        state=(AlertState.SENT if reached else AlertState.HELD).value,
        named=list(roster.on_call), reached=reached, not_reached=missed,
    )
    with get_alert_store().txn() as records:
        records[rec.id] = rec
    logger.info("on-call alert %s (%s): reached %d of %d named", rec.id, kind, len(reached), len(roster.on_call))
    return rec


def acknowledge(org_id: str, alert_id: str, person: str, now: datetime | None = None) -> AlertRecord:
    """An on-call person who received the alert acknowledges it. Before the window closes this stops the escalation;
    after it, the acknowledgement is recorded but the admins have already been asked."""
    now = now or datetime.now(timezone.utc)
    with get_alert_store().txn() as records:
        rec = records.get(alert_id)
        if rec is None or rec.org_id != org_id:
            raise KeyError(alert_id)
        if person not in rec.reached:
            raise PermissionError("only an on-call person who received this alert can acknowledge it")
        if not rec.acknowledged_by:
            rec.acknowledged_by, rec.acknowledged_at = person, _iso(now)
        if rec.state == AlertState.SENT.value:
            rec.state = AlertState.ACKNOWLEDGED.value
        return rec


async def tick(now: datetime | None = None) -> list[AlertRecord]:
    """Escalate every unacknowledged alert whose window has closed: every admin the org can reach is asked to approve
    the broadcast, all in the same tick. When an escalation reaches no admin, try again at ADMIN_RETRY_SECONDS after
    it (each try recorded, never every tick); after the last, record a final note and tell the raiser once. A try a
    crash left unrecorded is retried. Returns what it tried."""
    now = now or datetime.now(timezone.utc)
    claimed: list[AlertRecord] = []
    with get_alert_store().txn() as records:
        for rec in records.values():
            escalated = rec.state == AlertState.ESCALATED.value
            due = rec.state == AlertState.SENT.value and _when(rec.deadline) <= now
            crashed = (escalated and rec.admins_reached is None
                       and (not rec.admin_claimed_at
                            or _when(rec.admin_claimed_at) + timedelta(seconds=STALE_CLAIM_SECONDS) <= now))
            retry = (escalated and rec.admins_reached == [] and bool(rec.next_admin_attempt)
                     and _when(rec.next_admin_attempt) <= now)
            if due:
                rec.state, rec.escalated_at = AlertState.ESCALATED.value, _iso(now)
            if due or crashed or retry:
                rec.admins_reached, rec.admin_claimed_at = None, _iso(now)   # this try is claimed
                claimed.append(AlertRecord.from_dict(asdict(rec)))
    done = []
    for rec in claimed:
        from kintsugi.governance.consensus import get_consensus_gate

        if rec.admin_attempts == 0:
            try:
                get_consensus_gate().escalate(rec.consent_id, org_id=rec.org_id)
            except (KeyError, ValueError) as exc:  # decided, expired or gone: the admins still hear it went unanswered
                logger.info("consent %s not escalated: %s", rec.consent_id, exc)
        else:
            # A retry asks the admins to approve: if the request was decided meanwhile, that would be false. Stop.
            item = get_consensus_gate().get_item(rec.consent_id, org_id=rec.org_id)
            status = item.status.value if item is not None else "gone"
            if status not in ("PENDING", "ESCALATED"):
                with get_alert_store().txn() as records:
                    live = records[rec.id]
                    live.admins_reached, live.admin_claimed_at, live.next_admin_attempt = [], "", ""
                    live.final_note = f"the broadcast request is {status.lower()}, so no more tries"
                    done.append(AlertRecord.from_dict(asdict(live)))
                continue
        text = (f"{rec.message}\nNo on-call acknowledgement within {rec.ack_window_seconds // 60} minutes. The wide "
                f"broadcast is waiting for an admin's approval (request {rec.consent_id}).")
        org_admins = admins(rec.org_id)
        roster = load_roster(rec.org_id)
        reached, missed = await reach(org_admins, roster, set(org_admins), text)
        attempt = rec.admin_attempts + 1
        tell_raiser = False
        with get_alert_store().txn() as records:
            live = records[rec.id]
            live.admins_reached, live.admins_not_reached = reached, missed
            live.admin_attempts, live.admin_claimed_at = attempt, ""
            live.next_admin_attempt = ""
            if not reached and attempt < MAX_ADMIN_ATTEMPTS:
                live.next_admin_attempt = _iso(_when(live.escalated_at)
                                               + timedelta(seconds=ADMIN_RETRY_SECONDS[attempt - 1]))
            elif not reached:
                live.final_note = f"still no admin reached after {attempt} attempts"
                tell_raiser, live.raiser_told = not live.raiser_told, True
            done.append(AlertRecord.from_dict(asdict(live)))
        if tell_raiser:
            raiser = _person_name(rec.triggered_by)
            note = (f"{rec.message}\nStill no admin reached after {attempt} attempts: nobody has approved the wide "
                    f"broadcast (request {rec.consent_id}). If people need help now, don't wait for it.")
            told, _ = await reach([raiser] if raiser else [], roster, members(rec.org_id), note)
            with get_alert_store().txn() as records:
                records[rec.id].raiser_reached = bool(told)
        logger.warning("on-call alert %s escalation try %d: %d of %d admins reached", rec.id, attempt, len(reached),
                       len(org_admins))
    return done


def _person_name(identity: str) -> str:
    """The person behind an acting identity ("key:<id>"), or "" if the key names none."""
    from kintsugi.security.api_keys import person_of

    who = person_of(identity or "")
    return who[len("person:"):] if who.startswith("person:") else ""


def roster_problems() -> list[str]:
    """Entries that can't work, named at startup so a missing set-person is found before a raid, not during one
    (Vera, 2026-10-20): every on-call or contacts entry with no live key for that person in its org, every on-call
    person with no contact, and every admin no escalation could reach. An unreadable roster is itself a problem."""
    from kintsugi.config.settings import settings
    from kintsugi.security.api_keys import get_key_store

    path = Path(os.path.expanduser(settings.ONCALL_FILE))
    if not path.exists():
        return []
    try:
        orgs = sorted((json.loads(path.read_text() or "{}") or {}).keys())
        rosters = {org: load_roster(org) for org in orgs}
    except (ValueError, AttributeError) as exc:
        return [f"the on-call roster {path} can't be read ({type(exc).__name__}): every alert will hold"]
    problems = []
    for org, roster in rosters.items():
        live = members(org)
        for person in sorted(set(roster.on_call) | set(roster.contacts)):
            if person not in live:
                problems.append(f"{org}: {person!r} is in the on-call roster but has no live key with that person")
        for person in roster.on_call:
            if person in live and not roster.contacts.get(person):
                problems.append(f"{org}: on-call {person!r} has no contact, so no alert can reach them")
        for person in admins(org):
            if not roster.contacts.get(person):
                problems.append(f"{org}: admin {person!r} has no contact, so no escalation can reach them")
    unnamed = sorted({r.org_id for r in get_key_store().list()
                      if r.org_id in rosters and r.role == "admin" and not r.revoked_at and not r.person})
    for org in unnamed:
        problems.append(f"{org}: an admin key names no person, so escalations can't reach its holder")
    return problems


def get_alert(org_id: str, alert_id: str) -> AlertRecord | None:
    with get_alert_store().txn(write=False) as records:
        rec = records.get(alert_id)
        return rec if rec is not None and rec.org_id == org_id else None


def status_line(rec: AlertRecord) -> str:
    """What the person who raised the alert needs to know about who has it."""
    minutes = rec.ack_window_seconds // 60
    missed = "; ".join(f"{p}: {why}" for p, why in rec.not_reached.items())
    if rec.state == AlertState.HELD.value:
        if not rec.named:
            return "No on-call people are named for this deployment, so nobody has been alerted."
        return (f"None of the {len(rec.named)} on-call people could be reached ({missed}), so nobody has been "
                f"alerted.")
    line = f"Sent to on-call: {', '.join(rec.reached)}."
    if missed:
        line += f" Not reached: {missed}."
    if rec.state == AlertState.SENT.value:
        line += (f" If nobody acknowledges by {_when(rec.deadline).strftime('%H:%M')} UTC ({minutes} minutes), "
                 f"every admin is asked to approve the broadcast.")
    elif rec.state == AlertState.ACKNOWLEDGED.value:
        line += f" Acknowledged by {rec.acknowledged_by}."
    elif rec.state == AlertState.ESCALATED.value:
        if rec.admins_reached is None:
            line += f" No acknowledgement within {minutes} minutes: the admins are being asked."
        elif rec.admins_reached:
            line += (f" No acknowledgement within {minutes} minutes: every admin was asked "
                     f"({', '.join(rec.admins_reached)} reached).")
        elif rec.final_note:
            line += f" No acknowledgement within {minutes} minutes, and {rec.final_note}."
        else:
            nxt = (f"; next try {_when(rec.next_admin_attempt).strftime('%H:%M')} UTC" if rec.next_admin_attempt
                   else "")
            line += (f" No acknowledgement within {minutes} minutes, and no admin could be reached yet (try "
                     f"{rec.admin_attempts} of {MAX_ADMIN_ATTEMPTS}{nxt}).")
    return line


def public(rec: AlertRecord) -> dict:
    """The record as it is shown back: everything but the contacts, which it never holds."""
    return asdict(rec)
