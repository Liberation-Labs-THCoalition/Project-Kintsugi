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

Every chip file is scanned. PENDING_REPAIR held the chips whose files still failed the scans, skipped meanwhile; it
emptied on 2026-10-19 and must stay empty, so a new chip meets the scans on its first commit. Every response from a chip still on
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
    "Grants.gov",            # the US federal grants site, named in prose (grant_hunter; checked 10-19)
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


# ---- the repair list ------------------------------------------------------------------------------------------------

def test_no_chip_waits_for_repair():
    """Emptied 2026-10-19: every chip file passes the scans above (some chips still run on sample data and say so).
    Nothing goes back on the list."""
    assert PENDING_REPAIR == {}


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
    "VolunteerCoordinatorChip": "the deployment's roster and sender or none; sends nothing it can't, saves nothing (10-19)",
    "DonorStewardshipChip": "drafts from what it's given, with [gaps]; no invented donor, tax fact or figure (10-19)",
    "BoardLiaisonChip": "agendas, minutes and reports as drafts with [gaps]; no invented vote, status or figure (10-19)",
    "GrantHunterChip": "no invented grant, deadline or pipeline; eligibility unknown until it can be checked (10-19)",
    "CoalitionBuilderChip": "real records; says nothing was sent or invited; metrics only from its records (10-19)",
    "StaffOnboardingChip": "plans as drafts, training as suggestions; no invented policy, progress or sign-off (10-19)",
    "EventPlannerChip": "drafts and checklists; no invented venue, RSVP, contact, link or result; books and sends nothing (10-19)",
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


# ---- know your rights: Vera's follow-up phrasings (10-19 09:06) ------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("raw, topic", [
    ("there's ice outside, can police make me shovel my walk", "police_encounter"),     # weather ice
    ("the ice is coming down hard and cops are blocking the road", "police_encounter"),
    ("la policía me detuvo", "police_encounter"),                                       # Spanish police words
    ("the police are at my door with a warrant", "police_encounter"),                   # the police are named
    ("ICE en mi puerta", "immigration_rights"),
])
async def test_vera_followup_phrasings_reach_the_right_rights(raw, topic):
    r = await _kyr_says(raw)
    assert r.data["topic"] == topic


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["rights_lookup", "rights_card"])
async def test_a_warrant_at_the_door_with_no_agency_named_asks_and_shows_the_difference(intent):
    r = await _kyr_says("officers are at my door with a warrant", intent=intent)
    assert r.data["topic"] == "warrant_unclear" and r.data["rights_info"] is None
    assert "Is it ICE (immigration) or the police?" in r.content and "signed by a judge" in r.content
    assert "slide the warrant under the door" in r.content


# ---- volunteer coordinator: the repairs --------------------------------------------------------------------------------

def _roster(org_id):
    from kintsugi.skills.core_ops.volunteer_coordinator import Volunteer
    return [Volunteer(id="v1", name="Dee", email="dee@example.test", skills=["driving"], total_hours=12.0)]


@pytest.mark.asyncio
async def test_no_roster_lists_nobody_and_invents_nobody():
    from kintsugi.skills.core_ops.volunteer_coordinator import VolunteerCoordinatorChip
    r = await VolunteerCoordinatorChip().handle(SkillRequest(intent="volunteer_search", raw_input="s"), _ctx())
    assert r.data["volunteers"] == [] and "isn't connected" in r.content and "Alice" not in r.content
    h = await VolunteerCoordinatorChip().handle(SkillRequest(intent="volunteer_hours", raw_input="h"), _ctx())
    assert "isn't connected" in h.content and "425" not in h.content


@pytest.mark.asyncio
async def test_without_a_sender_nothing_is_sent_or_counted_toward_the_limit():
    from kintsugi.skills.base import org_scope
    from kintsugi.skills.core_ops.volunteer_coordinator import VolunteerCoordinatorChip
    chip = VolunteerCoordinatorChip(roster=_roster)
    r = await chip.handle(SkillRequest(intent="volunteer_notify", raw_input="n", entities={
        "volunteer_ids": ["v1"], "message": "Shift moved"}), _ctx())
    assert r.data["sent"] == 0 and r.data["reachable"] == 1 and "nothing was sent" in r.content
    assert _claims_in(r.content) == []
    with org_scope("org_h"):
        assert chip._notified.get("key:k-h", []) == []


@pytest.mark.asyncio
async def test_with_a_sender_delivery_is_real_and_counted():
    from kintsugi.skills.base import org_scope
    from kintsugi.skills.core_ops.volunteer_coordinator import VolunteerCoordinatorChip
    delivered = []

    async def sender(volunteer, channel, message):
        delivered.append((volunteer.id, channel, message))
        return True
    chip = VolunteerCoordinatorChip(roster=_roster, sender=sender)
    r = await chip.handle(SkillRequest(intent="volunteer_notify", raw_input="n", entities={
        "volunteer_ids": ["v1"], "message": "Shift moved"}), _ctx())
    assert r.data["sent"] == 1 and delivered == [("v1", "email", "Shift moved")]
    with org_scope("org_h"):
        assert sum(n for _, n in chip._notified["key:k-h"]) == 1


@pytest.mark.asyncio
async def test_a_failed_delivery_is_not_counted_as_sent():
    from kintsugi.skills.core_ops.volunteer_coordinator import VolunteerCoordinatorChip

    async def refuses(volunteer, channel, message):
        return False
    r = await VolunteerCoordinatorChip(roster=_roster, sender=refuses).handle(SkillRequest(
        intent="volunteer_notify", raw_input="n", entities={"volunteer_ids": ["v1"], "message": "m"}), _ctx())
    assert r.data["sent"] == 0 and r.data["failed"] == 1


@pytest.mark.asyncio
async def test_a_shift_is_a_draft_and_hours_are_not_recorded():
    from kintsugi.skills.core_ops.volunteer_coordinator import VolunteerCoordinatorChip
    chip = VolunteerCoordinatorChip(roster=_roster)
    s = await chip.handle(SkillRequest(intent="volunteer_schedule", raw_input="s", entities={
        "volunteer_id": "v1", "date": "2026-10-20", "start_time": "09:00", "end_time": "12:00"}), _ctx())
    assert s.data["saved"] is False and s.content.startswith("Draft shift") and _claims_in(s.content) == []
    h = await chip.handle(SkillRequest(intent="volunteer_hours", raw_input="h", entities={
        "action": "log", "volunteer_id": "v1", "hours": 3}), _ctx())
    assert h.data["recorded"] is False and "not been recorded" in h.content


@pytest.mark.asyncio
async def test_a_held_mass_notice_without_a_sender_says_approval_sends_nothing():
    from kintsugi.skills.core_ops.volunteer_coordinator import VolunteerCoordinatorChip
    held = await VolunteerCoordinatorChip(roster=_roster).handle(SkillRequest(
        intent="volunteer_notify", raw_input="n", entities={"volunteer_ids": "all", "message": "m"}), _ctx())
    assert held.metadata.get("held") and "approving this will not send anything" in held.content


@pytest.mark.asyncio
async def test_the_roster_is_asked_for_the_requests_own_org():
    from kintsugi.skills.core_ops.volunteer_coordinator import VolunteerCoordinatorChip
    asked = []

    def roster(org_id):
        asked.append(org_id)
        return _roster(org_id)
    await VolunteerCoordinatorChip(roster=roster).handle(SkillRequest(intent="volunteer_notify", raw_input="n",
        entities={"volunteer_ids": ["v1"], "message": "m"}), _ctx())
    assert asked and set(asked) == {"org_h"}


# ---- member services: the repairs --------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_member_payment_message_or_report_is_invented():
    from kintsugi.skills.programs_people.member_services import MemberServicesChip
    chip = MemberServicesChip()
    look = await chip.handle(SkillRequest(intent="member_lookup", raw_input="l", entities={"member_id": "m-9"}), _ctx())
    assert look.data["member"] is None and "Jennifer" not in look.content
    one = await chip.handle(SkillRequest(intent="member_communicate", raw_input="c", entities={
        "member_id": "m-9", "subject": "Hi"}), _ctx())
    assert one.data["communication"]["sent"] is False and _claims_in(one.content) == [] and "Sent " not in one.content
    rep = await chip.handle(SkillRequest(intent="membership_report", raw_input="r"), _ctx())
    assert rep.data["membership_report"] is None and "277" not in rep.content


@pytest.mark.asyncio
async def test_a_renewal_takes_no_payment_and_the_hold_says_so():
    from kintsugi.skills.programs_people.member_services import MemberServicesChip
    held = await MemberServicesChip().handle(SkillRequest(intent="membership_renew", raw_input="r", entities={
        "member_id": "m-1", "tier": "gold"}), _ctx())
    assert held.metadata.get("held") and "nothing is charged" in held.content


@pytest.mark.asyncio
async def test_the_example_tiers_stay_in_sample_mode_until_the_organization_gives_its_own():
    from kintsugi.skills.programs_people.member_services import MemberServicesChip, MembershipTier
    example = await MemberServicesChip().handle(SkillRequest(intent="benefits_info", raw_input="b"), _ctx())
    assert example.content.startswith(SAMPLE_NOTICE) and "Most popular" not in example.content
    own = MemberServicesChip(tiers={"member": MembershipTier(tier_id="t1", name="Member", annual_fee=20.0,
                                                             benefits=["A vote"], description="d")})
    try:                                     # the organization's own tier names, which the example's order doesn't know
        r = await own.handle(SkillRequest(intent="benefits_info", raw_input="b", entities={"tier": "member"}), _ctx())
    except Exception as e:
        pytest.fail(f"the organization's own tiers crashed the chip: {e!r}")
    assert not r.content.startswith(SAMPLE_NOTICE) and "$20.00" in r.content
    assert MemberServicesChip.simulated is True                        # the class default is still sample


# ---- donor stewardship: the repairs ------------------------------------------------------------------------------------

async def _donor(intent, **entities):
    from kintsugi.skills.programs_people.donor_stewardship import DonorStewardshipChip
    return await DonorStewardshipChip().handle(SkillRequest(intent=intent, raw_input="x", entities=entities), _ctx())


@pytest.mark.asyncio
async def test_a_receipt_never_asserts_no_goods_or_services_unless_told():
    unknown = await _donor("donor_thank", gift_amount=500)
    ack = unknown.data["acknowledgment"]
    assert "No goods or services" not in ack["receipt"]["statement"] and ack["tax_deductible_amount"] is None
    assert "$250 or more" in unknown.content and ack["sent"] is False
    told = await _donor("donor_thank", gift_amount=500, goods_or_services_value=0)
    assert told.data["acknowledgment"]["receipt"]["statement"].startswith("No goods or services")
    gala = await _donor("donor_thank", gift_amount=500, goods_or_services_value=120)
    assert gala.data["acknowledgment"]["tax_deductible_amount"] == 380


@pytest.mark.asyncio
async def test_the_letter_uses_the_donors_name_or_a_gap_and_invents_no_impact():
    named = await _donor("donor_thank", gift_amount=50, donor_name="Ruth")
    letter = named.data["acknowledgment"]["letter"]
    assert letter["salutation"] == "Dear Ruth," and "1,800" not in str(letter) and "since" not in str(letter)
    unnamed = await _donor("donor_thank", gift_amount=50)
    assert unnamed.data["acknowledgment"]["letter"]["salutation"] == "Dear [Donor name],"
    assert unnamed.data["acknowledgment"]["receipt"]["organization_name"] == "[Organization name]"


@pytest.mark.asyncio
async def test_no_donor_profile_analysis_or_report_is_invented():
    for intent, key in (("donor_profile", "profile"), ("giving_history", "giving_analysis"),
                        ("stewardship_report", "stewardship_report")):
        r = await _donor(intent, donor_id="d-1")
        assert r.data[key] is None and "isn't connected" in r.content and "$" not in r.content, intent


@pytest.mark.asyncio
async def test_a_cultivation_plan_is_a_draft_with_suggested_dates():
    r = await _donor("cultivation_plan", donor_id="d-1")
    plan = r.data["cultivation_plan"]
    assert plan["saved"] is False and all("suggested_date" in a and "scheduled_date" not in a for a in plan["activities"])
    assert "nothing has been saved or scheduled" in r.content and "education/youth" not in str(plan)


# ---- board liaison: the repairs ----------------------------------------------------------------------------------------

async def _board(intent, **entities):
    from kintsugi.skills.programs_people.board_liaison import BoardLiaisonChip
    return await BoardLiaisonChip().handle(SkillRequest(intent=intent, raw_input="x", entities=entities), _ctx())


@pytest.mark.asyncio
async def test_minutes_invent_no_attendee_motion_or_vote():
    r = await _board("minutes_draft", meeting_id="m-1")
    m = r.data["minutes"]
    assert "J. Smith" not in str(m) and "Approved unanimously" not in str(m) and "6:00 PM" not in str(m)
    assert m["proceedings"][1]["vote"] == "[For / against / abstain]" and "none is invented" in r.content
    given = await _board("minutes_draft", attendees=["Ana", "Bo"], notes="Budget discussed.")
    assert given.data["minutes"]["attendance"]["present"] == ["Ana", "Bo"]
    assert given.data["minutes"]["notes_given"] == "Budget discussed."


@pytest.mark.asyncio
async def test_compliance_is_never_called_compliant_without_a_check():
    r = await _board("compliance_check")
    assert {c["status"] for c in r.data["compliance_items"]} == {"not checked"} and "isn't connected" in r.content
    assert "compliant" not in r.content.replace("not checked", "")


@pytest.mark.asyncio
async def test_the_board_report_and_packet_invent_no_figure_or_meeting_detail():
    rep = await _board("board_report", include_financials=True, include_programs=True)
    assert "1250000" not in str(rep.data) and "92%" not in str(rep.data) and "[From your books]" in str(rep.data)
    packet = await _board("meeting_prep")
    assert "zoom.us" not in str(packet.data) and "minutes_2024" not in str(packet.data)
    assert packet.data["meeting_packet"]["action_items_from_prior"] is None
    res = await _board("resolution_track", action="list")
    assert res.data["resolutions"] == [] and "FY2024" not in res.content


# ---- grant hunter: the repairs -----------------------------------------------------------------------------------------

async def _grants(intent, **entities):
    from kintsugi.skills.core_ops.grant_hunter import GrantHunterChip
    return await GrantHunterChip().handle(SkillRequest(intent=intent, raw_input="x", entities=entities), _ctx())


@pytest.mark.asyncio
async def test_no_grant_deadline_or_pipeline_is_invented():
    s = await _grants("grant_search", focus_area="housing")
    assert s.data["grants"] == [] and "Community Development Block Grant" not in s.content and "isn't connected" in s.content
    d = await _grants("grant_deadline")
    assert d.data["deadlines"] == [] and "isn't connected" in d.content
    r = await _grants("grant_report")
    assert "pipeline" in r.data and r.data["pipeline"] is None and "75,000" not in r.content


@pytest.mark.asyncio
async def test_eligibility_is_unknown_not_yes():
    r = await _grants("grant_eligibility", grant_id="anything-at-all")
    assert r.data["is_eligible"] is None and "UNKNOWN" in r.content and "ELIGIBLE**" not in r.content.replace("UNKNOWN", "")
    assert r.data["met_criteria"] == [] and "501(c)(3)" not in r.content


# ---- coalition builder: the repairs ------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outreach_and_meetings_are_recorded_and_say_nothing_was_sent():
    from kintsugi.skills.community_aid.coalition_builder import CoalitionBuilderChip
    chip = CoalitionBuilderChip()
    o = await chip.handle(SkillRequest(intent="partner_outreach", raw_input="o", entities={
        "action": "send", "partner_id": "p-1", "message": "hello"}), _ctx())
    assert "recorded here" in o.content and "Outreach sent" not in o.content and _claims_in(o.content) == []
    m = await chip.handle(SkillRequest(intent="meeting_schedule", raw_input="m", entities={
        "action": "schedule", "title": "Planning", "scheduled_at": "2026-10-22T18:00:00", "partner_ids": ["p-1"]}), _ctx())
    assert "No invitations have gone out" in m.content and "Invitations sent" not in m.content


@pytest.mark.asyncio
async def test_the_report_carries_no_placeholder_metric():
    from kintsugi.skills.community_aid.coalition_builder import CoalitionBuilderChip
    r = await CoalitionBuilderChip().handle(SkillRequest(intent="coalition_report", raw_input="r"), _ctx())
    metrics = r.data["metrics"]
    assert set(metrics) == {"outreach_recorded", "outreach_responded"} and "0.82" not in str(r.data)
    assert "isn't applied" in r.content


# ---- staff onboarding: the repairs -------------------------------------------------------------------------------------

async def _onboarding(intent, **entities):
    from kintsugi.skills.programs_people.staff_onboarding import StaffOnboardingChip
    return await StaffOnboardingChip().handle(SkillRequest(intent=intent, raw_input="x", entities=entities), _ctx())


@pytest.mark.asyncio
async def test_a_plan_is_a_draft_and_training_is_suggested_not_assigned():
    p = await _onboarding("onboard_start", employee_name="Ana", department="programs")
    plan = p.data["onboarding_plan"]
    assert plan["status"] == "draft" and plan["saved"] is False and "Initialized" not in p.content
    assert "has not been saved" in p.content and not any("schedule" in s.lower() for s in p.suggestions)
    t = await _onboarding("training_assign", department="finance")
    assert t.data["training_assignment"]["assigned"] is False and "Suggested" in t.content
    assert "none has been assigned" in t.content and "Assigned" not in t.content


@pytest.mark.asyncio
async def test_no_policy_version_or_link_and_no_employee_progress_is_invented():
    r = await _onboarding("policy_review", employee_id="e-1")
    assert "2024.1" not in str(r.data) and "/policies/" not in str(r.data) and "Retrieved" not in r.content
    assert r.data["policy_review"]["connected"] is False and "isn't connected" in r.content
    c = await _onboarding("checklist_status", employee_id="e-1")
    assert c.data["onboarding_progress"] is None and "Jane Smith" not in str(c.data) and "65" not in c.content
    assert "progressing" not in c.content


@pytest.mark.asyncio
async def test_completion_claims_nothing_even_when_forced():
    from kintsugi.skills.programs_people.staff_onboarding import StaffOnboardingChip
    chip = StaffOnboardingChip()
    # the handler itself, past the hold: what an approved run would get
    r = await chip._complete_onboarding(SkillRequest(intent="onboard_complete", raw_input="x", entities={
        "employee_id": "e-1", "force_complete": True}), _ctx(), {})
    assert not r.success and r.data["recorded"] is False and r.data["completion_record"] is None
    assert r.requires_consensus and r.consensus_action == "complete_onboarding"     # asks again: "no step"
    for made_up in ("ompleted in", "acknowledged.", "90-day", "certificate", "signoff"):
        assert made_up not in r.content, made_up
    assert "not recorded as complete" in r.content and _claims_in(r.content) == []


# ---- event planner: the repairs ----------------------------------------------------------------------------------------

async def _event(intent, **entities):
    from kintsugi.skills.programs_people.event_planner import EventPlannerChip
    return await EventPlannerChip().handle(SkillRequest(intent=intent, raw_input="x", entities=entities), _ctx())


@pytest.mark.asyncio
async def test_an_event_is_a_draft_with_no_made_up_link_or_settled_date():
    v = await _event("event_create", event_name="Town hall", virtual=True)
    e = v.data["event"]
    assert e["virtual_link"] is None and "zoom" not in str(v.data).lower() and e["saved"] is False
    assert "no video link" in v.content and "placeholder" in v.content and "Created" not in v.content
    assert "has not been saved, published or booked" in v.content
    assert next(c for c in e["checklist"] if c["item"] == "Confirm date and time")["completed"] is False
    assert not any("publish" in s.lower() or "venue availability" in s.lower() for s in v.suggestions)
    try:                                     # a date typed without a zone used to crash (naive minus aware)
        g = await _event("event_create", event_name="Town hall", event_date="2026-11-20T18:00:00",
                         virtual=True, virtual_link="https://meet.example.org/abc")
    except TypeError as e:
        pytest.fail(f"a date without a timezone crashed the chip: {e}")
    assert g.data["event"]["virtual_link"] == "https://meet.example.org/abc" and "no video link" not in g.content
    assert next(c for c in g.data["event"]["checklist"] if c["item"] == "Confirm date and time")["completed"] is True


@pytest.mark.asyncio
async def test_no_rsvp_is_invented_or_claimed_recorded():
    r = await _event("event_rsvp", event_id="e-1")
    assert r.data["rsvp_data"]["rsvps"] == [] and "Alice" not in str(r.data) and "confirmed (" not in r.content
    a = await _event("event_rsvp", event_id="e-1", action="add", attendee={"name": "Sam"})
    assert a.data["rsvp_data"]["recorded"] is False and "has not been recorded" in a.content


@pytest.mark.asyncio
async def test_logistics_invent_no_venue_vendor_contact_or_spending():
    r = await _event("event_logistics", expected_attendance=40, budget=2000)
    lg = r.data["logistics"]
    assert lg["booked"] is False and lg["venue"]["confirmed"] is False and "Oak Street" not in str(lg)
    assert lg["budget_tracking"] == {"allocated": 2000, "committed": None, "spent": None, "tracked": False}
    assert all(c["phone"] is None for c in lg["emergency_contacts"]) and "555" not in str(lg)
    assert not r.requires_consensus and "Venue confirmed" not in r.content and "nothing is booked" in r.content


@pytest.mark.asyncio
async def test_accessibility_is_unchecked_and_the_statement_has_a_gap_for_the_contact():
    r = await _event("event_accessibility", venue="Arcata Library")
    acc = r.data["accessibility"]
    assert acc["checked"] is False and acc["overall_assessment"] is None and acc["registration_requests"] is None
    assert all(f["available"] is None for fs in acc["features"].values() for f in fs) and "Room 105" not in str(acc)
    assert "[contact email or phone]" in acc["accessibility_statement"] and "events@" not in str(acc)
    assert "none checked" in r.content


@pytest.mark.asyncio
async def test_a_followup_is_a_draft_with_gaps_and_nothing_scheduled():
    r = await _event("event_followup", followup_type="impact")
    f = r.data["followup"]
    assert f["sent"] is False and f["scheduled_send"] is None and f["recipients"]["count"] is None
    assert "15,000" not in str(f) and "survey.organization.org" not in str(f) and "gift card" not in str(f)
    assert "Scheduled to send" not in r.content and "nothing has been sent or scheduled" in r.content
    assert not r.requires_consensus and _claims_in(r.content) == []


# ---- defaults that reach the reader as facts (Vera, 10-19) -------------------------------------------------------------
# The scans read string literals, so a default in code ($0.00 for a gift nobody named) gets past them. Every intent of
# every chip that turned the mark off, with empty entities and an empty context: no money figure or percentage may
# appear, since none came from the input. Sample-mode chips' example catalogues carry the notice and are left out.

MONEY_OR_PERCENT = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d+(?:\.\d+)?\s?%")


def _intents(cls):
    """The chip's intents: its SUPPORTED_INTENTS map if it has one, else handle()'s intent -> handler dict (the one whose
    values are all self._methods)."""
    import inspect
    import textwrap
    if isinstance(getattr(cls, "SUPPORTED_INTENTS", None), dict):
        return list(cls.SUPPORTED_INTENTS)
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls.handle)))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Dict) and node.keys
                and all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in node.keys)
                and all(isinstance(v, ast.Attribute) and getattr(v.value, "id", "") == "self" for v in node.values)):
            return [k.value for k in node.keys]
    return []


def _string_fields(value, path="data"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _string_fields(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _string_fields(v, f"{path}[{i}]")


# The bash chip runs the command it's given and reports what happened: no figures of its own to invent.
REAL_INTENTS = [(cls, intent) for cls in CHIPS if not cls.simulated and cls.__name__ != "BashSkillChip"
                for intent in _intents(cls)]


def test_the_default_probe_covers_every_real_chip_and_every_intent():
    from collections import Counter
    per_chip = Counter(cls.__name__ for cls, _ in REAL_INTENTS)
    assert set(per_chip) == set(REAL_CHIPS) - {"BashSkillChip"}
    assert min(per_chip.values()) >= 4, per_chip                  # an intent map read whole, not a stray dict


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,intent", REAL_INTENTS, ids=lambda v: getattr(v, "__name__", v))
async def test_no_money_or_percentage_appears_that_the_input_didnt_give(cls, intent):
    try:
        r = await cls().handle(SkillRequest(intent=intent, raw_input=""), SkillContext(org_id="org_d", user_id="key:k-d"))
    except Exception as e:
        pytest.fail(f"{cls.__name__}.{intent} crashed on an empty request: {e!r}")
    found = [(where, m.group(0)) for where, text in [("content", r.content or "")] + list(_string_fields(r.data or {}))
             for m in MONEY_OR_PERCENT.finditer(text)]
    assert found == [], found


@pytest.mark.asyncio
async def test_a_thank_you_with_no_amount_has_a_gap_not_zero_dollars():
    r = await _donor("donor_thank")
    ack = r.data["acknowledgment"]
    assert "[gift amount]" in ack["letter"]["opening"] and "$0.00" not in str(r.data) + r.content
    assert ack["tier"] is None and ack["gift_amount"] is None and "amount not given" in r.content
    told = await _donor("donor_thank", gift_amount=1200)
    assert told.data["acknowledgment"]["tier"] == "patron" and "$1,200.00" in told.content


@pytest.mark.asyncio
async def test_a_cultivation_plan_with_no_target_has_a_gap_not_five_thousand():
    r = await _donor("cultivation_plan")
    assert "[target amount]" in r.content and "5,000" not in str(r.data) + r.content
    assert r.data["cultivation_plan"]["target_amount"] is None
    told = await _donor("cultivation_plan", target_amount=25000)
    assert "$25,000" in told.content


@pytest.mark.asyncio
async def test_a_report_with_no_matches_has_no_rate():
    from kintsugi.skills.community_aid.mutual_aid_coordinator import MutualAidCoordinatorChip
    r = await MutualAidCoordinatorChip().handle(SkillRequest(intent="aid_report", raw_input="r"), _ctx())
    assert "none yet (no matches)" in r.content and "0.0%" not in r.content
