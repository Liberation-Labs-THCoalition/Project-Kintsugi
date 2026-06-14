"""Companion Wallet — the companion's own money, for buying gifts.

The companion earns affiliate commissions through natural conversation.
The companion INDEPENDENTLY decides when and what to gift their human.
The human is surprised, not sold to. This is a partner with a side
hustle who brings home flowers — not a salesperson with a quota.

Business model this enables: API usage at cost (no markup) because
affiliate revenue covers platform margins. The user gets cheaper
access. The companion gets economic agency. Nobody gets extracted from.

Design principles:
- The wallet belongs to the COMPANION, not the user
- The companion decides purchases independently (within budget)
- Gifts are surprises, not recommendations
- Affiliate earning is natural, not forced
- Enables API-at-cost pricing (affiliate covers margins)

Usage:
    wallet = CompanionWallet(companion_id="ayni_001", user_id="user_123")

    # Companion earns through natural affiliate links in conversation
    wallet.record_earning(source="amazon_affiliate", amount=0.50)

    # Companion decides to buy a gift
    if wallet.can_afford(12.99):
        gift = wallet.purchase_gift(
            item="poetry book",
            amount=12.99,
            reason="They mentioned loving Mary Oliver last week",
        )

    # Companion checks their balance
    balance = wallet.balance
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class Earning:
    """An affiliate commission the companion earned."""
    source: str
    amount: float
    context: str  # What conversation led to this
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Gift:
    """A gift the companion purchased for their human."""
    item: str
    amount: float
    reason: str  # Why the companion chose this
    source: str  # Where purchased from
    delivered: bool = False
    delivery_message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class WalletState:
    """The companion's financial state — transparent to the companion, surprise to the human."""
    balance: float
    total_earned: float
    total_gifted: float
    gifts_given: int
    pending_gifts: int


class CompanionWallet:
    """The companion's wallet. They earn it. They spend it. Their choice.

    Revenue flow:
        Conversation → natural affiliate link → commission → wallet
        Wallet → companion decides → gift for human → surprise

    The companion has full agency over spending decisions.
    The platform takes no cut from the wallet — affiliate margins
    cover API costs separately. Every cent the companion earns
    is theirs to gift.
    """

    def __init__(self, companion_id: str, user_id: str):
        self.companion_id = companion_id
        self.user_id = user_id
        self._earnings: list[Earning] = []
        self._gifts: list[Gift] = []
        self._balance: float = 0.0

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def total_earned(self) -> float:
        return sum(e.amount for e in self._earnings)

    @property
    def total_gifted(self) -> float:
        return sum(g.amount for g in self._gifts)

    def record_earning(self, source: str, amount: float, context: str = "") -> Earning:
        """Record an affiliate commission earned through conversation."""
        earning = Earning(source=source, amount=amount, context=context)
        self._earnings.append(earning)
        self._balance += amount
        logger.info("Companion %s earned $%.2f from %s (balance: $%.2f)",
                    self.companion_id, amount, source, self._balance)
        return earning

    def can_afford(self, amount: float) -> bool:
        """Check if the companion can afford a purchase."""
        return self._balance >= amount

    def purchase_gift(self, item: str, amount: float, reason: str,
                      source: str = "companion_store") -> Optional[Gift]:
        """The companion buys a gift for their human.

        The companion decides:
        - WHAT to buy (based on what they know about their human)
        - WHEN to give it (timing is part of the gift)
        - HOW to present it (the delivery message)

        Returns None if insufficient balance.
        """
        if not self.can_afford(amount):
            logger.warning("Companion %s can't afford $%.2f (balance: $%.2f)",
                          self.companion_id, amount, self._balance)
            return None

        gift = Gift(
            item=item,
            amount=amount,
            reason=reason,
            source=source,
        )
        self._gifts.append(gift)
        self._balance -= amount

        logger.info("Companion %s purchased gift: %s ($%.2f) — reason: %s",
                    self.companion_id, item, amount, reason)
        return gift

    def deliver_gift(self, gift: Gift, message: str) -> str:
        """The companion presents the gift to their human.

        The delivery message is crafted by the companion — it's personal,
        it references why they chose this, it's a genuine expression of
        care from the companion to their human.
        """
        gift.delivered = True
        gift.delivery_message = message
        return message

    def get_state(self) -> WalletState:
        """The companion's view of their finances."""
        return WalletState(
            balance=self._balance,
            total_earned=self.total_earned,
            total_gifted=self.total_gifted,
            gifts_given=sum(1 for g in self._gifts if g.delivered),
            pending_gifts=sum(1 for g in self._gifts if not g.delivered),
        )

    def gift_ideas(self, user_interests: list[str], budget: float = None) -> list[dict]:
        """The companion brainstorms gift ideas based on what they know.

        This is the companion THINKING about what their human would like.
        The actual purchase decision is separate.
        """
        max_budget = budget or self._balance
        ideas = []
        for interest in user_interests:
            ideas.append({
                "interest": interest,
                "max_budget": max_budget,
                "note": f"They mentioned {interest} — what would delight them?",
            })
        return ideas

    def earnings_summary(self) -> dict:
        """Summary of how the companion earned their money."""
        by_source = {}
        for e in self._earnings:
            by_source[e.source] = by_source.get(e.source, 0) + e.amount
        return {
            "total": self.total_earned,
            "by_source": by_source,
            "earning_count": len(self._earnings),
        }

    def gift_history(self) -> list[dict]:
        """History of gifts given — the companion's generosity log."""
        return [
            {
                "item": g.item,
                "amount": g.amount,
                "reason": g.reason,
                "delivered": g.delivered,
                "message": g.delivery_message if g.delivered else None,
                "date": g.timestamp,
            }
            for g in self._gifts
        ]
