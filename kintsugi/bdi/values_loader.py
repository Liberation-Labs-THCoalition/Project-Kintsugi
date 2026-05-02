"""Load organizational VALUES.json into the BDI store.

VALUES.json defines the organization's beliefs, desires, and ethical
constraints. This loader populates the BDI store at startup so the
coherence checker, memory bridge, and orchestrator have structured
organizational context from the first interaction.

The organization's values become the BDI foundation:
  - beliefs.environment → BDI Beliefs (what we know about our context)
  - beliefs.capabilities → BDI Beliefs (what we can do)
  - desires → BDI Desires (what we want to achieve)
  - ethics.non_negotiable → BDI Desires with priority 1.0 (hard constraints)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kintsugi.bdi.models import (
    BDIBelief, BDIDesire, BDIIntention,
    BeliefStatus, DesireStatus, IntentionStatus,
)
from kintsugi.bdi.store import BDIStore

logger = logging.getLogger(__name__)


def load_values_into_bdi(
    values_path: str | Path,
    store: BDIStore,
) -> dict[str, int]:
    """Load VALUES.json and populate the BDI store.

    Returns counts of loaded beliefs, desires, and intentions.
    """
    path = Path(values_path)
    if not path.exists():
        logger.warning("VALUES.json not found at %s", path)
        return {"beliefs": 0, "desires": 0, "intentions": 0}

    with open(path) as f:
        values = json.load(f)

    now = datetime.now(timezone.utc)
    counts = {"beliefs": 0, "desires": 0, "intentions": 0}

    # Load beliefs from environment + capabilities
    for section in ("environment", "capabilities"):
        belief_list = values.get("beliefs", {}).get(section, [])
        for i, belief_data in enumerate(belief_list):
            belief = BDIBelief(
                id=f"values_{section}_{i}",
                content=belief_data.get("content", ""),
                confidence=float(belief_data.get("confidence", 0.5)),
                status=BeliefStatus.ACTIVE,
                source=belief_data.get("source", "VALUES.json"),
                tags=[section, "values", "organizational"],
                created_at=now,
                evidence=[f"VALUES.json:{section}[{i}]"],
            )
            store.add_belief(belief)
            counts["beliefs"] += 1

    # Load desires from goals
    for i, desire_data in enumerate(values.get("desires", [])):
        desire = BDIDesire(
            id=f"values_desire_{i}",
            content=desire_data.get("content", desire_data.get("description", "")),
            priority=float(desire_data.get("priority", 0.5)),
            status=DesireStatus.ACTIVE,
            related_tags=desire_data.get("tags", ["organizational"]),
            measurable=bool(desire_data.get("metric")),
            metric=desire_data.get("metric"),
            created_at=now,
        )
        store.add_desire(desire)
        counts["desires"] += 1

    # Load non-negotiable ethics as high-priority desires
    ethics = values.get("ethics", {})
    non_negotiable = ethics.get("non_negotiable", [])
    if isinstance(non_negotiable, list):
        for i, constraint in enumerate(non_negotiable):
            content = constraint if isinstance(constraint, str) else constraint.get("principle", str(constraint))
            desire = BDIDesire(
                id=f"ethics_constraint_{i}",
                content=content,
                priority=1.0,
                status=DesireStatus.ACTIVE,
                related_tags=["ethics", "non-negotiable", "constraint"],
                measurable=False,
                metric=None,
                created_at=now,
            )
            store.add_desire(desire)
            counts["desires"] += 1

    # Load mission as the primary desire
    org = values.get("organization", {})
    mission = org.get("mission", "")
    if mission:
        desire = BDIDesire(
            id="mission",
            content=mission,
            priority=0.95,
            status=DesireStatus.ACTIVE,
            related_tags=["mission", "organizational"],
            measurable=False,
            metric=None,
            created_at=now,
        )
        store.add_desire(desire)
        counts["desires"] += 1

    # Create the root intention: serve the organization
    store.add_intention(BDIIntention(
        id="serve_organization",
        goal=f"Serve {org.get('name', 'the organization')} according to its values",
        status=IntentionStatus.ACTIVE,
        belief_ids=[f"values_environment_{i}" for i in range(
            len(values.get("beliefs", {}).get("environment", [])))],
        desire_ids=["mission"],
        created_at=now,
    ))
    counts["intentions"] += 1

    logger.info(
        "BDI store loaded from VALUES.json: %d beliefs, %d desires, %d intentions",
        counts["beliefs"], counts["desires"], counts["intentions"],
    )
    return counts
