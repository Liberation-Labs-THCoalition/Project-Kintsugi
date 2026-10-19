"""What a skill chip may tell a person about what it did (CC, 2026-10-19).

A chip says only what it did. Three rules, enforced by tests/test_chip_honesty_20261019.py:

- **No claimed action.** A chip says something was sent, notified, alerted, dispatched, scheduled or shared only when
  its code did that through a connected integration. Writing a record into the chip's own store is "recorded here",
  not "sent".
- **No invented facts.** Without a connected source, a chip returns no records and says the source isn't connected.
  It never fills the gap with sample pantries, listings, landlords, clinics, hotlines, grants, cooperatives,
  balances, transactions or results. A person can't tell sample data from their own, and some of them act on it in an
  emergency.
- **No false offers.** Suggestions name only things this chip can do.

For someone who may be in danger, a chip with nothing connected points to help that exists across the US, and to
nothing it made up. Deployments that know their local hotlines should connect them, not hard-code them here.
"""
from __future__ import annotations

# National US services, stable for years: 911 (emergencies), 211 (local referrals for food, housing, legal help and
# more, run by United Way and partners), 988 (the Suicide & Crisis Lifeline, since July 2022). The only phone numbers
# allowed in chip code (the honesty test enforces it).
US_DANGER = "If anyone is in immediate danger, call 911."
US_REFERRALS = "For local food, housing, legal and other help, call 211."
US_CRISIS = "For a mental-health crisis, call or text 988."
US_HELP = f"{US_DANGER} {US_REFERRALS}"

NOBODY_CONTACTED = "Nobody has been contacted by this system."

# Put first in every response from a chip still on sample data (BaseSkillChip.simulated; kintsugi/skills/base.py).
SAMPLE_NOTICE = ("**Sample mode.** This skill isn't connected to your organization's systems yet, so the figures, "
                 "records and contacts below may be placeholders rather than yours, and nothing has been sent to anyone.")


def not_connected(source: str, consequence: str) -> str:
    """The standard sentence for a missing integration: what isn't connected, and what that means for this request.

    >>> not_connected("A food pantry directory", "I can't list pantries near you")
    "A food pantry directory isn't connected to this deployment, so I can't list pantries near you."
    """
    return f"{source} isn't connected to this deployment, so {consequence}."
