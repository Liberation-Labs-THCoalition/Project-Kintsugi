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
    "grant_hunter.py": "invented grants with fake URLs; every org told it's eligible",
    "volunteer_coordinator.py": "'Sent N notifications' when nothing is sent; invented roster",
    "donor_stewardship.py": "every letter to 'Sarah'; invented receipts, profiles and totals",
    "member_services.py": "renewals 'processed', receipts and emails 'sent'; invented members and figures",
    "coalition_builder.py": "'Outreach sent', 'Invitations sent'; placeholder metrics as measured",
    "board_liaison.py": "invented minutes, motions, votes, compliance status and board report",
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
ALLOWED_URLS: set[str] = {
    "https://www.aclu.org",  # the ACLU's own site (know_your_rights; checked 10-19)
    "neweconomy.net",        # the New Economy Coalition's site (solidarity_economy; checked 10-19)
}


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
    "CrisisResponseChip": "keeps real incident records; says nothing was broadcast or dispatched (10-19)",
    "HousingNavigatorChip": "lists nothing it can't look up; tenant law as questions to ask locally (10-19)",
    "KnowYourRightsChip": "US-wide rights for police and immigration only; English said plainly; no invented org (10-19)",
    "FoodAccessChip": "lists no invented pantry or meal; no SNAP verdict from stale limits; donations not recorded, said so (10-19)",
    "MutualAidEnhancedChip": "never refuses a person for naming a fear; says nothing was posted without its core (10-19)",
    "MutualAidCoordinatorChip": "real records; says nobody is notified and no contact details are shared (10-19)",
    "ResourceRedistributionChip": "real records; says pickups and partners are recorded, nobody told (10-19)",
    "SolidarityEconomyChip": "formation guidance and real networks; no invented co-op, balance, loan or cost (10-19)",
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


# ---- crisis response: the repairs --------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_crisis_alert_is_recorded_and_says_nobody_was_notified():
    from kintsugi.skills.community_aid.crisis_response import CrisisResponseChip
    chip = CrisisResponseChip()
    r = await chip.handle(SkillRequest(intent="crisis_alert", raw_input="x", entities={
        "crisis_type": "natural_disaster", "severity": "high", "title": "Flooding", "location": "Riverside"}), _ctx())
    from kintsugi.skills.base import org_scope
    with org_scope("org_h"):
        assert r.data["incident_id"] in chip._incidents                    # the record is real
    assert "nobody has been notified" in r.content and "911" in r.content and _claims_in(r.content) == []
    low = await chip.handle(SkillRequest(intent="crisis_alert", raw_input="x", entities={"severity": "low"}), _ctx())
    assert "911" not in low.content and _claims_in(low.content) == []


@pytest.mark.asyncio
async def test_a_held_critical_alert_says_approval_notifies_nobody_and_what_to_do_now():
    from kintsugi.skills.community_aid.crisis_response import CrisisResponseChip
    chip = CrisisResponseChip()
    held = await chip.handle(SkillRequest(intent="crisis_alert", raw_input="x", entities={"severity": "critical"}), _ctx())
    assert held.metadata.get("held") and "approving this will not notify anyone" in held.content and "911" in held.content
    result = await _approve_and_run(chip, held)
    assert "nobody has been notified" in result["content"] and _claims_in(result["content"]) == []


@pytest.mark.asyncio
async def test_mobilizing_with_no_volunteers_on_record_says_so_and_dispatches_nobody():
    from kintsugi.skills.community_aid.crisis_response import CrisisResponseChip
    chip = CrisisResponseChip()
    r = await chip.handle(SkillRequest(intent="crisis_alert", raw_input="x", entities={"severity": "medium"}), _ctx())
    m = await chip.handle(SkillRequest(intent="mobilize_response", raw_input="m",
                                       entities={"incident_id": r.data["incident_id"]}), _ctx())
    assert m.data["volunteers_mobilized"] == 0 and "none was marked deployed" in m.content
    assert _claims_in(m.content) == []


@pytest.mark.asyncio
async def test_the_alert_log_records_that_nothing_was_sent():
    from kintsugi.skills.base import org_scope
    from kintsugi.skills.community_aid.crisis_response import CrisisResponseChip
    chip = CrisisResponseChip()
    await chip.handle(SkillRequest(intent="crisis_alert", raw_input="x", entities={"severity": "medium"}), _ctx())
    with org_scope("org_h"):
        entry = chip._alert_log[-1]
    assert entry["sent"] is False and "sent_at" not in entry


# ---- housing navigator: the repairs ------------------------------------------------------------------------------------

async def _housing(intent, contacts=None, **entities):
    from kintsugi.skills.community_aid.housing_navigator import HousingNavigatorChip
    return await HousingNavigatorChip(contacts=contacts).handle(SkillRequest(intent=intent, raw_input="x", entities=entities), _ctx())


@pytest.mark.asyncio
async def test_no_listing_application_or_landlord_is_made_up():
    s = await _housing("housing_search", city="Oakland", bedrooms=2)
    assert s.data["units"] == [] and "isn't connected" in s.content and "Oak Street" not in s.content
    v = await _housing("voucher_status", application_id="APP-1")
    assert v.data["connected"] is False and "Waitlist Position" not in v.content and "#234" not in v.content
    landlord = await _housing("landlord_lookup", property_address="456 Oak St")
    assert landlord.data["landlord_id"] is None and "Bay Area Properties" not in landlord.content


@pytest.mark.asyncio
async def test_tenant_rights_are_questions_never_a_rule_for_everywhere():
    r = await _housing("tenant_rights", state="TX")
    assert "Rent increases limited to annual cap" not in r.content and "24-48 hour" not in r.content
    assert "questions to ask locally" in r.content and "Many don't" in r.content


@pytest.mark.asyncio
async def test_eviction_help_names_only_configured_lines():
    none = await _housing("eviction_defense", stage="notice")
    assert "isn't connected" in none.content and "211" in none.content and not PHONE.search(none.content)
    mine = await _housing("eviction_defense", contacts={"eviction_legal_help": "LINE-E"}, stage="court")
    assert "LINE-E" in mine.content and "DO NOT miss your court date" in mine.content


# ---- know your rights: the repairs -------------------------------------------------------------------------------------

async def _kyr(intent, contacts=None, **entities):
    from kintsugi.skills.community_aid.know_your_rights import KnowYourRightsChip
    return await KnowYourRightsChip(contacts=contacts).handle(SkillRequest(intent=intent, raw_input="x", entities=entities), _ctx())


@pytest.mark.asyncio
async def test_police_rights_are_never_given_as_another_topics_rights():
    for topic in ("tenant_rights", "worker_rights", "voting_rights", "disability_rights"):
        r = await _kyr("rights_lookup", topic=topic, state="CA")
        assert r.data["rights_info"] is None and "remain silent" not in r.content, topic
    police = await _kyr("rights_lookup", topic="police_encounter")
    assert "remain silent" in police.content and "Last updated" not in police.content


@pytest.mark.asyncio
async def test_immigration_rights_say_a_lawyer_isnt_appointed_and_name_the_judges_warrant():
    r = await _kyr("rights_lookup", topic="immigration_rights")
    assert "signed by a judge" in r.content and "isn't appointed" in r.content


@pytest.mark.asyncio
async def test_a_rights_card_says_it_is_in_english_and_names_no_invented_hotline():
    es = await _kyr("rights_card", topic="police_encounter", language="es")
    assert "this is in English, not es" in es.content and "write your local number here" in es.content
    assert not PHONE.search(es.content) and es.data["rights_card"]["language"] == "en"
    mine = await _kyr("rights_card", contacts={"legal_hotline": "LINE-K"}, topic="police_encounter")
    assert "Legal help: LINE-K" in mine.content
    tenant = await _kyr("rights_card", topic="tenant_rights")
    assert tenant.data["rights_card"] is None


@pytest.mark.asyncio
async def test_clinics_and_legal_help_are_the_deployments_own_or_none():
    clinics = await _kyr("legal_clinic", location="Oakland")
    assert clinics.data["clinics"] == [] and "123 Main St" not in clinics.content and "isn't connected" in clinics.content
    help_ = await _kyr("legal_resource")
    assert "isn't connected" in help_.content and not PHONE.search(help_.content) and not URL.search(help_.content)
    mine = await _kyr("legal_resource", contacts={"immigration_legal_help": "LINE-I"})
    assert "LINE-I" in mine.content


# ---- food access: the repairs ------------------------------------------------------------------------------------------

async def _food(intent, contacts=None, **entities):
    from kintsugi.skills.community_aid.food_access import FoodAccessChip
    return await FoodAccessChip(contacts=contacts).handle(SkillRequest(intent=intent, raw_input="x", entities=entities), _ctx())


@pytest.mark.asyncio
async def test_no_pantry_or_meal_program_is_made_up():
    p = await _food("pantry_find", zip_code="94612")
    assert p.data["pantries"] == [] and "555" not in p.content and "211" in p.content
    m = await _food("meal_schedule", meal_type="lunch")
    assert m.data["programs"] == [] and "Oak St" not in m.content
    mine = await _food("pantry_find", contacts={"food_pantry_line": "LINE-F"})
    assert "LINE-F" in mine.content


@pytest.mark.asyncio
async def test_snap_gives_no_verdict_or_benefit_estimate():
    r = await _food("snap_help", household_size=3, monthly_income=2000)
    assert r.data["eligibility"] is None and "Likely Eligible" not in r.content and "May Not Qualify" not in r.content
    assert "Estimated Monthly Benefit" not in r.content and "Apply even if you're unsure" in r.content
    assert "don't have to give one or their immigration status" in r.content


@pytest.mark.asyncio
async def test_a_donation_is_not_recorded_and_says_so():
    r = await _food("food_donate", quantity=20, pickup=True)
    assert r.data["recorded"] is False and r.data["pickup_scheduled"] is False
    assert "No pickup has been scheduled" in r.content and "Donation ID" not in r.content
    held = await _food("food_donate", quantity=500)
    assert held.metadata.get("held") and "approving this records nothing" in held.content


# ---- mutual aid (enhanced): the shield and the fallbacks ---------------------------------------------------------------

async def _mae(raw, intent="need_post", **entities):
    from kintsugi.skills.community_aid.mutual_aid_enhanced import MutualAidEnhancedChip
    return await MutualAidEnhancedChip().handle(SkillRequest(intent=intent, raw_input=raw, entities=entities), _ctx())


@pytest.mark.asyncio
async def test_the_shield_never_refuses_rice_notices_or_a_person_afraid_of_ice():
    for raw in ("I need rice and beans", "my eviction notice came", "help with my office move", "any advice?"):
        r = await _mae(raw)
        assert r.success and "shield_commitment" not in r.data, raw
    afraid = await _mae("I'm scared ICE will come, I need a place to stay")
    assert afraid.success and afraid.data["shield_commitment"] is True
    assert afraid.content.startswith("This group's guidelines rule out contacting immigration enforcement")
    asked = await _mae("do you do a background check?")
    assert asked.success and "background checks" in asked.content


@pytest.mark.asyncio
async def test_without_its_core_nothing_is_claimed_posted_or_reviewed():
    need = await _mae("I need groceries", category="food")
    assert need.data["posted"] is False and _claims_in(need.content) == [] and "We'll notify" not in need.content
    offer = await _mae("I can drive people", intent="offer_post")
    assert offer.data["posted"] is False and "has been posted" not in offer.content
    match = await _mae("match these", intent="match_request")
    assert match.data["recorded"] is False and "coordinator will review" not in match.content


@pytest.mark.asyncio
async def test_the_notification_bridge_reports_nothing_sent():
    from kintsugi.skills.community_aid.mutual_aid_enhanced import MutualAidEnhancedChip
    assert await MutualAidEnhancedChip()._kintsugi_notify("someone-123", "hello") is False


# ---- mutual aid coordinator and redistribution: the repairs ------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_unmatched_need_is_not_promised_a_notification():
    from kintsugi.skills.community_aid.mutual_aid_coordinator import MutualAidCoordinatorChip
    r = await MutualAidCoordinatorChip().handle(SkillRequest(intent="need_post", raw_input="n", entities={
        "category": "housing", "description": "A room", "location": "Arcata"}), _ctx())
    assert r.data["potential_matches"] == 0
    assert all("We'll notify" not in s for s in r.suggestions) and any("nobody is notified" in s for s in r.suggestions)


@pytest.mark.asyncio
async def test_a_recorded_pickup_says_nobody_has_been_told():
    from kintsugi.skills.community_aid.resource_redistribution import ResourceRedistributionChip
    chip = ResourceRedistributionChip()
    s = await chip.handle(SkillRequest(intent="surplus_report", raw_input="s", entities={
        "resource_type": "shelf_stable", "quantity": 10, "unit": "boxes", "location": "Arcata"}), _ctx())
    assert all("We'll alert" not in x for x in s.suggestions)
    p = await chip.handle(SkillRequest(intent="pickup_schedule", raw_input="p", entities={
        "surplus_id": s.data["surplus_id"], "delivery_location": "Eureka"}), _ctx())
    assert p.success and "Nobody has been told" in p.content and _claims_in(p.content) == []


# ---- solidarity economy: the repairs -----------------------------------------------------------------------------------

async def _se(intent, **entities):
    from kintsugi.skills.community_aid.solidarity_economy import SolidarityEconomyChip
    return await SolidarityEconomyChip().handle(SkillRequest(intent=intent, raw_input="x", entities=entities), _ctx())


@pytest.mark.asyncio
async def test_no_coop_balance_member_or_loan_is_made_up():
    coops = await _se("coop_search", location="Oakland")
    assert coops.data["coops"] == [] and "Green City" not in coops.content
    balance = await _se("time_bank", action="balance")
    assert "12.5" not in balance.content and balance.data["connected"] is False
    browse = await _se("time_bank", action="browse")
    assert "John D." not in browse.content
    loans = await _se("cdfi_loan", amount=50000)
    assert loans.data["loans"] == [] and "Cooperative Fund of the Northeast" not in loans.content and "%" not in loans.content


@pytest.mark.asyncio
async def test_a_small_exchange_records_nothing_and_says_so():
    r = await _se("time_bank", action="exchange", hours=2, service="tutoring", recipient="m-2")
    assert r.data["recorded"] is False and "no credits have moved" in r.content and "Pending Verification" not in r.content


@pytest.mark.asyncio
async def test_formation_guidance_names_costs_without_inventing_amounts():
    r = await _se("coop_start", coop_type="worker", members=4)
    assert "vary a lot by state" in r.content and "$" not in r.content


# ---- know your rights hears what people type (Vera, 10-19) -------------------------------------------------------------

async def _kyr_says(raw, intent="rights_lookup", **entities):
    from kintsugi.skills.community_aid.know_your_rights import KnowYourRightsChip
    return await KnowYourRightsChip().handle(SkillRequest(intent=intent, raw_input=raw, entities=entities), _ctx())


@pytest.mark.asyncio
@pytest.mark.parametrize("raw, topic, says", [
    ("ICE is at my door, what are my rights", "immigration_rights", "signed by a judge"),
    ("there's an immigration raid on our block", "immigration_rights", "signed by a judge"),
    ("ice agents outside the building", "immigration_rights", "signed by a judge"),
    ("the police pulled me over, what are my rights", "police_encounter", "remain silent"),
    ("can I be arrested for filming cops", "police_encounter", "remain silent"),
    ("what are my rights at the protest tomorrow", "protest_rights", "remain silent"),
])
async def test_what_a_person_types_reaches_its_rights(raw, topic, says):
    r = await _kyr_says(raw)
    assert r.data["topic"] == topic and says in r.content


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["what are my rights", "I slipped on ice at work", "my lease ends in March"])
async def test_nothing_recognised_offers_the_three_never_a_dead_end(raw):
    r = await _kyr_says(raw)
    assert r.success and r.data["topic"] is None and r.data["choices"] == list(
        __import__("kintsugi.skills.community_aid.know_your_rights", fromlist=["x"]).KnowYourRightsChip.WITH_RIGHTS)
    assert "police encounter" in r.content and "immigration encounter" in r.content and "protest" in r.content


@pytest.mark.asyncio
async def test_the_fallback_reads_cleanly_with_no_state():
    r = await _kyr_says("x", topic="tenant_rights")
    assert "I can't look up tenant rights here" in r.content
    assert "federal" not in r.content and "your general" not in r.content and "Which is it?" in r.content


@pytest.mark.asyncio
async def test_a_card_follows_what_the_person_typed():
    r = await _kyr_says("make me a card for when ICE comes", intent="rights_card")
    assert r.data["rights_card"]["topic"] == "immigration_rights" and "signed by a judge" in r.content
