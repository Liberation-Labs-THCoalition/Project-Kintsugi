"""Skill chips say only what they did (kintsugi/skills/honesty.py; CC, 2026-10-19).

An audit of every chip found stubs ("In production, this would...") whose sample data reached people as fact: a raid
report told "legal observers are being dispatched" when nothing was sent, vanity hotlines given to people facing
eviction or detention, invented pantries, listings, landlords, grants, balances and financial statements. These tests
scan every chip's source, so a new stub can't bring them back:

- no phone number but 911, 211 and 988 (deployments connect their own local lines);
- no URL or email address but the few listed here, each checked;
- no hard-coded calendar date standing in for a real one;
- no prose that claims an action (sent, notified, alerted, dispatched, scheduled, shared, "will call"...) unless the
  same sentence says it didn't happen, or the claim is listed here with the code that makes it true.

Chips not yet repaired are listed in PENDING_REPAIR, with what's left, and skipped by the scans; the list may only
shrink (a listed chip with nothing left fails until it's taken off). Meanwhile every response from a chip still on
sample data says so first (BaseSkillChip.simulated), and these tests check that too.
"""
from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

import pytest

from kintsugi.skills.base import BaseSkillChip, SkillContext, SkillDomain, SkillRequest, SkillResponse
from kintsugi.skills.honesty import SAMPLE_NOTICE

SKILLS = Path(__file__).resolve().parent.parent / "kintsugi" / "skills"
CHIP_FILES = sorted(p for p in SKILLS.rglob("*.py") if p.name not in ("__init__.py", "honesty.py"))


@functools.lru_cache(maxsize=None)
def _strings(path: Path):
    """(line, text) for every string literal in a file, an f-string's literal parts joined with {} for each field."""
    return tuple(_walk_strings(path))


def _walk_strings(path: Path):
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    inside_fstring = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            inside_fstring.update(id(v) for v in node.values)
            yield node.lineno, "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
                and id(node) not in inside_fstring):
            yield node.lineno, node.value


# Chip file -> what's still wrong in it. Repaired chips come off; nothing new goes on.
PENDING_REPAIR: dict[str, str] = {
    "event_planner.py": "invented venue, Zoom link, contacts, RSVPs, accessibility, results; 'Scheduled to send'",
    "know_your_rights.py": "vanity hotlines and invented clinics; police rights shown for every topic",
    "food_access.py": "invented pantries, meal programs and a past pickup date with 555 numbers",
    "solidarity_economy.py": "invented coops, CDFI terms and a time-bank balance",
    "grant_hunter.py": "invented grants with fake URLs; every org told it's eligible",
    "crisis_response.py": "claims responders, leadership and emergency services notified",
    "housing_navigator.py": "invented listings, landlord record, waitlist position, eviction hotline",
    "volunteer_coordinator.py": "'Sent N notifications' when nothing is sent; invented roster",
    "donor_stewardship.py": "every letter to 'Sarah'; invented receipts, profiles and totals",
    "member_services.py": "renewals 'processed', receipts and emails 'sent'; invented members and figures",
    "coalition_builder.py": "'Outreach sent', 'Invitations sent'; placeholder metrics as measured",
    "mutual_aid_coordinator.py": "'We'll notify you' with no notification path",
    "board_liaison.py": "invented minutes, motions, votes, compliance status and board report",
    "resource_redistribution.py": "'We'll alert partners' with no alerting",
    "mutual_aid_enhanced.py": "fallback 'posted' claims; the shield refuses 'rice' and 'notice'",
    "staff_onboarding.py": "invented progress and sign-offs; '90-day review scheduled'",
}


def _all_strings(include_pending=False):
    for path in CHIP_FILES:
        if path.name in PENDING_REPAIR and not include_pending:
            continue
        for line, text in _strings(path):
            yield path.relative_to(SKILLS.parent.parent).as_posix(), line, text


def test_the_scan_sees_every_chip():
    names = {p.stem for p in CHIP_FILES}
    assert {"rapid_response", "crisis_response", "food_access", "housing_navigator", "know_your_rights",
            "finance_assistant", "grant_hunter", "event_planner"} <= names
    assert len(CHIP_FILES) >= 25


# ---- phone numbers ---------------------------------------------------------------------------------------------------

PHONE = re.compile(r"\b1-8\d\d-[0-9A-Z]|\(\d{3}\)\s*\d{3}-\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b|\b555-\d{4}\b")


def test_no_phone_number_but_911_211_and_988():
    found = [(f, n, t[:90]) for f, n, t in _all_strings() if PHONE.search(t)]
    assert found == [], "invented or hard-coded phone numbers:\n" + "\n".join(map(str, found))


def test_the_phone_pattern_catches_what_we_found():
    for bad in ("1-800-LEGAL-NOW", "1-866-3-HUNGRY", "(510) 555-1234", "1-800-221-5689", "call 415.555.0100"):
        assert PHONE.search(bad), bad
    for fine in ("call 911", "call 211", "call or text 988", "FY2024", "$1,650/month"):
        assert not PHONE.search(fine), fine


# ---- URLs and email addresses ----------------------------------------------------------------------------------------

URL = re.compile(r"https?://|\bwww\.|\b[\w-]+\.(?:org|com|gov|net|edu)(?:/|\b)|[\w.+-]+@[\w-]+\.\w+")
# Each checked by hand. A deployment's own links belong in its configuration, not in chip code.
ALLOWED_URLS: set[str] = set()


def test_no_url_or_email_but_the_checked_ones():
    found = [(f, n, t[:90]) for f, n, t in _all_strings()
             if URL.search(t) and not any(a in t for a in ALLOWED_URLS)]
    assert found == [], "unchecked links or addresses:\n" + "\n".join(map(str, found))


def test_the_url_pattern_catches_what_we_found():
    for bad in ("https://grants.gov/example/001", "candid.org/example/001", "Apply at rentrelief.org",
                "tenantlaw@legalaid.org", "aclu.org/contact"):
        assert URL.search(bad), bad
    for fine in ("Organization", "e.g. a church or a library", "U.S. Department"):
        assert not URL.search(fine), fine


# ---- hard-coded dates ------------------------------------------------------------------------------------------------

def test_no_hard_coded_calendar_date():
    """datetime(2024, 1, 15) shown as a last transaction, a clinic or a pickup is a date nobody chose."""
    found = []
    for path in (p for p in CHIP_FILES if p.name not in PENDING_REPAIR):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("datetime", "date")
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, int)):
                found.append((path.name, node.lineno))
    month_day = [(f, n, t[:90]) for f, n, t in _all_strings()
                 if re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}\b", t)]
    assert found == [] and month_day == [], f"hard-coded dates: {found} {month_day}"


# ---- claimed actions -------------------------------------------------------------------------------------------------

CLAIM = re.compile(
    r"\b(?:has|have|had|was|were|is|are|been)\s+(?:been\s+)?(?:sent|notified|alerted|dispatched|shared|scheduled|"
    r"submitted|contacted|distributed|activated|initiated|mobilized)\b"
    r"|\b(?:being|be)\s+(?:dispatched|distributed|notified|alerted|sent)\b"
    r"|\bwill\s+(?:call|contact|reach out|be in touch|notify|alert|follow up)\b"
    r"|\bwe'll\s+(?:notify|alert|contact|call|let you know|reach out)\b"
    r"|\b(?:invitations?|outreach|notifications?|reminders?|alerts?)\s+sent\b|\bsent\s+to\b"
    r"|\bscheduled\s+(?:to\s+send|for|:)|\bscheduled\b\s*$"
    r"|\bresponders notified\b|\bteams? (?:notified|dispatched|alerted)\b|\bnotified\b",
    re.IGNORECASE,
)
NEGATED = re.compile(r"\b(?:not|nobody|no one|nothing|never|isn't|hasn't|haven't|wasn't|won't|can't|cannot|no)\b",
                     re.IGNORECASE)
# (file, text fragment) -> the code that makes the claim true. Empty until a chip really performs one.
TRUE_CLAIMS: dict[tuple[str, str], str] = {}


def _claims(include_pending=False):
    for f, n, t in _all_strings(include_pending):
        if " " not in t.strip():
            continue  # identifiers and dict keys, not prose
        if CLAIM.search(t) and not NEGATED.search(t) and not any(f == tf and frag in t for tf, frag in TRUE_CLAIMS):
            yield f, n, t[:110]


def test_no_prose_claims_an_action_the_code_didnt_take():
    found = list(_claims())
    assert found == [], f"{len(found)} claimed action(s):\n" + "\n".join(map(str, found))


def test_the_claim_pattern_catches_what_we_found():
    for bad in ("Legal observers are being dispatched", "Rapid response team has been alerted",
                "Responders Notified: {}", "Bail fund coordinator will call within 2 hours",
                "We'll notify you when a match is found", "Invitations sent to {} partners.",
                "Scheduled to send in 24 hours.", "Volunteers have been notified and are being dispatched to {}.",
                "Leadership and emergency services notified.", "Outreach sent to {} via {}.",
                "A bail fund coordinator will contact you"):
        assert CLAIM.search(bad) and not NEGATED.search(bad), bad
    for fine in ("Nobody has been contacted by this system.", "Nothing was sent.",
                 "Drafted, not sent: review it before sending.", "Recorded here. No one has been notified."):
        assert not (CLAIM.search(fine) and not NEGATED.search(fine)), fine


# ---- the ratchet -----------------------------------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _scan_everything():
    """Every chip's scan findings, pending ones included, computed once: (file, text) pairs."""
    found = [(f, t) for f, n, t in _all_strings(True) if PHONE.search(t) or URL.search(t)]
    return tuple(found + [(f, t) for f, n, t in _claims(True)])


def _violations(name):
    out = [t for f, t in _scan_everything() if f.endswith("/" + name)]
    path = next(p for p in CHIP_FILES if p.name == name)
    for node in ast.walk(ast.parse(path.read_text())):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("datetime", "date")
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, int)):
            out.append(f"date at line {node.lineno}")
    return out


@pytest.mark.parametrize("name", sorted(PENDING_REPAIR))
def test_a_chip_waiting_for_repair_still_needs_it(name):
    """Fixed chips come off the list, so the scans cover them from then on."""
    assert any(p.name == name for p in CHIP_FILES), f"{name} isn't a chip"
    assert _violations(name), f"{name} passes every scan now: take it off PENDING_REPAIR"


# ---- the sample-mode mark --------------------------------------------------------------------------------------------

def _shipped_chips():
    import importlib
    import inspect
    import pkgutil
    import kintsugi.skills
    for mod in pkgutil.walk_packages(kintsugi.skills.__path__, "kintsugi.skills."):
        importlib.import_module(mod.name)
    seen, stack = [], list(BaseSkillChip.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if cls.__module__.startswith("kintsugi.skills.") and not inspect.isabstract(cls) and cls not in seen:
            seen.append(cls)
    return sorted(seen, key=lambda c: c.__name__)


CHIPS = _shipped_chips()
# Shipped chips that do only real work, and why. Nobody turns the mark off without saying so here.
REAL_CHIPS = {
    "BashSkillChip": "runs the command it's given, in a sandbox, and reports what happened",
    "RapidResponseChip": "says nobody was alerted and nothing sent; gives only configured lines, else 211 (10-19)",
}


def test_only_the_listed_chips_turn_the_mark_off():
    assert {c.__name__ for c in CHIPS if not c.simulated} == set(REAL_CHIPS)


def _first_intent(cls):
    """The first key of the intent -> handler map in the chip's handle(), read from its source."""
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls.handle)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and node.keys and all(isinstance(k, ast.Constant) for k in node.keys):
            return node.keys[0].value
    return None


SAMPLE = [c for c in CHIPS if c.simulated]


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", SAMPLE, ids=lambda c: c.__name__)
async def test_every_sample_chip_says_so_first(cls):
    intent = _first_intent(cls)
    assert intent, f"no intent map found in {cls.__name__}.handle"
    r = await cls().handle(SkillRequest(intent=intent, raw_input="test"), SkillContext(org_id="org_h", user_id="key:k-h"))
    if (r.metadata or {}).get("held"):
        pytest.skip("held for consent: a hold is real, and isn't marked")
    assert r.content.startswith(SAMPLE_NOTICE), r.content[:120]
    assert r.data.get("simulated") is True and r.metadata.get("simulated") is True


class _Real(BaseSkillChip):
    name = "test_honesty_real"
    description = "does what it says"
    domain = SkillDomain.OPERATIONS
    simulated = False

    async def handle(self, request, context):
        return SkillResponse(content="done", data={"n": 1})


class _Sample(BaseSkillChip):
    name = "test_honesty_sample"
    description = "placeholders"
    domain = SkillDomain.OPERATIONS
    real_intents = frozenset({"count"})

    async def handle(self, request, context):
        return SkillResponse(content=f"{request.intent}: 3 volunteers", data={"n": 3})


class _Twice(_Sample):
    name = "test_honesty_twice"

    async def handle(self, request, context):
        return await super().handle(request, context)


def _ctx():
    return SkillContext(org_id="org_h", user_id="key:k-h")


@pytest.mark.asyncio
async def test_the_mark_is_first_and_in_data_and_metadata():
    r = await _Sample().handle(SkillRequest(intent="report", raw_input="r"), _ctx())
    assert r.content == f"{SAMPLE_NOTICE}\n\nreport: 3 volunteers"
    assert r.data == {"n": 3, "simulated": True} and r.metadata == {"simulated": True}


@pytest.mark.asyncio
async def test_a_real_chip_and_a_real_intent_are_not_marked():
    assert (await _Real().handle(SkillRequest(intent="x", raw_input="x"), _ctx())).content == "done"
    r = await _Sample().handle(SkillRequest(intent="count", raw_input="c"), _ctx())
    assert r.content == "count: 3 volunteers" and "simulated" not in r.data


@pytest.mark.asyncio
async def test_a_chip_wrapped_twice_is_marked_once():
    r = await _Twice().handle(SkillRequest(intent="report", raw_input="r"), _ctx())
    assert r.content.count(SAMPLE_NOTICE) == 1


# ---- rapid response: the repairs ---------------------------------------------------------------------------------------

def _claims_in(text):
    """Lines of a response that claim an action without saying it didn't happen."""
    return [line for line in text.splitlines() if CLAIM.search(line) and not NEGATED.search(line)]


def _approve_and_run(chip, held, org="org_h"):
    from kintsugi.governance import consumer
    from kintsugi.governance.consensus import get_consensus_gate
    gate = get_consensus_gate()
    if gate.approve(held.data["consent_id"], "key:k-a1", org_id=org).status.value == "PENDING":
        gate.approve(held.data["consent_id"], "key:k-a2", org_id=org)

    class One:
        def get(self, name):
            return chip
    return consumer.execute_approved(held.data["consent_id"], org, One())


@pytest.mark.asyncio
async def test_a_raid_report_says_at_once_that_approval_alerts_nobody_and_what_to_do():
    from kintsugi.skills.community_aid.rapid_response import RapidResponseChip
    held = await RapidResponseChip().handle(SkillRequest(intent="raid_alert", raw_input="raid", entities={
        "area": "Downtown", "urgency": "critical"}), _ctx())
    assert held.metadata.get("held")
    assert "approving this will not alert anyone" in held.content and "don't wait" in held.content
    assert "211" in held.content and "911" not in held.content  # no police number during a raid
    configured = await RapidResponseChip(contacts={"rapid_response_hotline": "LINE-A"}).handle(
        SkillRequest(intent="raid_alert", raw_input="raid"), _ctx())
    assert "LINE-A" in configured.content


@pytest.mark.asyncio
async def test_an_approved_raid_report_still_alerts_nobody_and_says_so():
    from kintsugi.skills.community_aid.rapid_response import RapidResponseChip
    chip = RapidResponseChip()
    held = await chip.handle(SkillRequest(intent="raid_alert", raw_input="raid", entities={"urgency": "critical"}), _ctx())
    result = await _approve_and_run(chip, held)
    assert result["success"] and result["data"]["sent"] is False and result["data"]["responders_notified"] == 0
    assert "nobody has been alerted" in result["content"] and "911" not in result["content"]
    assert _claims_in(result["content"]) == []


@pytest.mark.asyncio
async def test_a_bail_request_promises_no_coordinator_and_names_only_a_configured_fund():
    from kintsugi.skills.community_aid.rapid_response import RapidResponseChip
    chip = RapidResponseChip(contacts={"bail_fund": "FUND-B"})
    held = await chip.handle(SkillRequest(intent="bail_request", raw_input="bail"), _ctx())
    assert "will not move money" in held.content and "FUND-B" in held.content
    result = await _approve_and_run(chip, held)
    assert "hasn't reached anyone" in result["content"] and "FUND-B" in result["content"]
    assert "will call" not in result["content"] and result["data"]["sent"] is False


@pytest.mark.asyncio
async def test_the_legal_hotline_is_the_deployments_or_none():
    from kintsugi.skills.community_aid.rapid_response import RapidResponseChip
    none = await RapidResponseChip().handle(SkillRequest(intent="legal_hotline", raw_input="h"), _ctx())
    assert none.data["number"] is None and "isn't connected" in none.content and not PHONE.search(none.content)
    mine = await RapidResponseChip(contacts={"legal_hotline": "LINE-L"}).handle(
        SkillRequest(intent="legal_hotline", raw_input="h"), _ctx())
    assert mine.data["number"] == "LINE-L" and "LINE-L" in mine.content


@pytest.mark.asyncio
async def test_no_safe_place_is_made_up():
    from kintsugi.skills.community_aid.rapid_response import RapidResponseChip
    r = await RapidResponseChip().handle(SkillRequest(intent="safe_location", raw_input="s"), _ctx())
    assert r.data["locations_available"] == 0 and "HAVEN" not in r.content and "isn't connected" in r.content
    mine = await RapidResponseChip(contacts={"safe_location_line": "LINE-S"}).handle(
        SkillRequest(intent="safe_location", raw_input="s"), _ctx())
    assert "LINE-S" in mine.content
