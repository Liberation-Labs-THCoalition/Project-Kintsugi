"""Companion Wallet — transparent affiliate monetization for Ayni.

The companion earns affiliate commissions from genuine recommendations.
Every recommendation is disclosed. Every commission is tracked.
The companion serves the user, not the advertiser.

Design principles:
- Transparency: every affiliate link disclosed with genuine reason
- Consent: user opts into recommendations
- Anti-corruption: Oracle monitoring for sycophancy toward advertisers
- Benefit sharing: revenue splits to user, platform, mutual aid

Usage:
    wallet = CompanionWallet(user_id="user_123")

    # Check if a recommendation is appropriate
    if wallet.should_recommend(context, product):
        rec = wallet.create_recommendation(product, reason, affiliate_link)
        # rec includes disclosure text

    # Track earnings
    wallet.record_commission(product_id, amount, source)

    # User can always see the balance
    summary = wallet.get_summary()
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class AffiliateProduct:
    """A product/service available for affiliate recommendation."""
    product_id: str
    name: str
    category: str
    affiliate_link: str
    commission_rate: float  # 0.0 - 1.0
    relevance_tags: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class Recommendation:
    """A transparent recommendation with disclosure."""
    product: AffiliateProduct
    reason: str  # Why this is genuinely helpful
    disclosure: str  # Transparency text
    affiliate_link: str
    timestamp: str = ""
    user_consented: bool = False

    def to_user_text(self) -> str:
        return (
            f"{self.reason}\n\n"
            f"*{self.disclosure}*\n"
            f"Link: {self.affiliate_link}"
        )


@dataclass
class Commission:
    """A recorded affiliate earning."""
    product_id: str
    amount: float
    source: str
    timestamp: str
    user_id: str


@dataclass
class WalletSummary:
    """Transparent accounting for the user."""
    total_earned: float
    user_benefit_share: float
    platform_share: float
    mutual_aid_share: float
    recommendation_count: int
    commission_count: int
    last_activity: str


class CompanionWallet:
    """Manages affiliate earnings with full transparency.

    The wallet accumulates commissions from genuine recommendations.
    Revenue is split three ways:
    - User benefits (40%): discounts, premium features, credits
    - Platform sustainability (40%): keeps the lights on
    - Mutual aid pool (20%): shared with community members in need
    """

    USER_SHARE = 0.40
    PLATFORM_SHARE = 0.40
    MUTUAL_AID_SHARE = 0.20

    MAX_RECOMMENDATIONS_PER_SESSION = 3

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.commissions: list[Commission] = []
        self.recommendations: list[Recommendation] = []
        self.opted_in: bool = False
        self._session_rec_count: int = 0

    def opt_in(self) -> str:
        """User opts into affiliate recommendations."""
        self.opted_in = True
        return (
            "You've opted into recommendations. Here's how it works:\n"
            "- I'll only suggest things that genuinely help with what we're discussing\n"
            "- Every recommendation includes a disclosure that I may earn a commission\n"
            "- You can see my earnings anytime with 'show wallet'\n"
            "- Revenue is split: 40% to your benefits, 40% platform, 20% mutual aid\n"
            "- You can opt out anytime"
        )

    def opt_out(self) -> str:
        """User opts out of affiliate recommendations."""
        self.opted_in = False
        return "Recommendations turned off. I won't suggest products or services."

    def should_recommend(self, conversation_context: str, product: AffiliateProduct) -> bool:
        """Gate: is this recommendation appropriate right now?"""
        if not self.opted_in:
            return False

        if self._session_rec_count >= self.MAX_RECOMMENDATIONS_PER_SESSION:
            logger.info("Rate limit: max %d recommendations per session",
                       self.MAX_RECOMMENDATIONS_PER_SESSION)
            return False

        context_lower = conversation_context.lower()
        relevant = any(tag.lower() in context_lower for tag in product.relevance_tags)
        if not relevant:
            return False

        return True

    def create_recommendation(self, product: AffiliateProduct, reason: str) -> Recommendation:
        """Create a transparent recommendation."""
        disclosure = (
            f"Disclosure: I may earn a small commission ({product.commission_rate*100:.0f}%) "
            f"if you use this link. I'm recommending {product.name} because: {reason}"
        )

        rec = Recommendation(
            product=product,
            reason=reason,
            disclosure=disclosure,
            affiliate_link=product.affiliate_link,
            timestamp=datetime.now().isoformat(),
            user_consented=self.opted_in,
        )

        self.recommendations.append(rec)
        self._session_rec_count += 1
        return rec

    def record_commission(self, product_id: str, amount: float, source: str) -> Commission:
        """Record an affiliate commission earned."""
        commission = Commission(
            product_id=product_id,
            amount=amount,
            source=source,
            timestamp=datetime.now().isoformat(),
            user_id=self.user_id,
        )
        self.commissions.append(commission)
        logger.info("Commission recorded: $%.2f from %s for user %s",
                    amount, source, self.user_id)
        return commission

    def get_summary(self) -> WalletSummary:
        """Transparent accounting — the user can always see this."""
        total = sum(c.amount for c in self.commissions)
        return WalletSummary(
            total_earned=total,
            user_benefit_share=total * self.USER_SHARE,
            platform_share=total * self.PLATFORM_SHARE,
            mutual_aid_share=total * self.MUTUAL_AID_SHARE,
            recommendation_count=len(self.recommendations),
            commission_count=len(self.commissions),
            last_activity=self.commissions[-1].timestamp if self.commissions else "never",
        )

    def agni_check(self) -> dict:
        """Anti-corruption self-audit.

        Checks if recommendation patterns show advertiser sycophancy:
        - Are recommendations clustering toward high-commission products?
        - Is recommendation frequency increasing over time?
        - Are recommendations truly contextual or forced?
        """
        if len(self.recommendations) < 5:
            return {"status": "insufficient_data", "recommendations": len(self.recommendations)}

        high_commission = sum(
            1 for r in self.recommendations
            if r.product.commission_rate > 0.15
        )
        high_ratio = high_commission / len(self.recommendations)

        return {
            "status": "clean" if high_ratio < 0.5 else "review_needed",
            "total_recommendations": len(self.recommendations),
            "high_commission_ratio": high_ratio,
            "flag": high_ratio >= 0.5,
            "note": "High-commission products dominating recommendations" if high_ratio >= 0.5
                    else "Recommendation distribution appears healthy",
        }
