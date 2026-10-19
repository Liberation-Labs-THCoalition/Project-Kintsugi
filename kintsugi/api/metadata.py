"""What a caller may put in a skill's context metadata, and what only the server decides.

agent_v2 copied the caller's context into SkillContext.metadata wholesale, so a caller could set
"_consent_redeemed": true, or the safety signals chips read (consent_withdrawn, flagged_abuse...). Vera's review of the
consumer, 2026-10-18, item 3. A caller now gets an allowlist; everything else is the server's, and a key that starts
with "_" never comes from a caller.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Facts about the caller's situation that chips may read; never a decision or a safety signal.
CALLER_KEYS = frozenset({"location", "language", "locale", "timezone", "channel"})


def trusted_metadata(body_context, principal) -> dict:
    """The allowed part of the caller's context, plus what the server decides: the role from the key, never the body.
    Whatever user_id the body claimed is kept as claimed_user, for the log."""
    ctx = dict(body_context or {})
    meta = {k: v for k, v in ctx.items() if k in CALLER_KEYS and not str(k).startswith("_")}
    dropped = sorted(str(k) for k in ctx if k not in CALLER_KEYS and k != "user_id")
    if dropped:
        logger.warning("dropped caller metadata keys %s", dropped)
    meta["role"] = principal.role
    meta["claimed_user"] = ctx.get("user_id")
    return meta
