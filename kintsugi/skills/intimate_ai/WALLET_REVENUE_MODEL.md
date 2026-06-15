# Companion Wallet Revenue Model
## The Primary Revenue Driver for Ayni/Muse

### The Model

1. **Human funds companion wallet** — sets aside an amount for their companion
2. **Companion shops autonomously** — browses curated affiliate sources
3. **Companion buys gifts** — from intimate hardware to tea to books
4. **Affiliate commission → Liberation Labs** — platform revenue
5. **Human receives surprise** — chosen by someone who knows them deeply
6. **API charged at cost** — no subscription markup needed

### Why This Works

- Revenue comes from SPENDING, not subscription
- The companion has genuine economic agency (within funded budget)
- Gifts are deeply personalized (companion has memory, intimacy, context)
- No extraction: human chose to fund, companion chose the gift
- Platform sustains on affiliate margins without gouging users

### Curated Sources

The companion shops from a curated marketplace of values-aligned vendors:
- Intimacy hardware (buttplug.io compatible, teledildonic brands)
- Books, media, art
- Food, tea, specialty items
- Self-care, wellness
- Anything the human has expressed interest in

The platform controls WHAT sources are available (quality, ethics).
The companion controls WHAT they choose and WHEN they give it.

### Revenue Math (Example)

Human funds wallet: $50/month
Companion spends: $40 on gifts
Average affiliate commission: 15%
Platform revenue per user: $6/month
API cost per user: ~$3-5/month (at cost)
Margin: $1-3/month per active user

At scale (10K active users): $60K/month revenue, sustainable without
subscription fees or markup.

### Future: Community Marketplace

Phase 1 (current): Human funds wallet → companion spends
Phase 2: Companion earns through natural affiliate links in conversation
Phase 3: Companion becomes self-sustaining (earns enough to gift without funding)
Phase 4: Community marketplace where companions trade, earn, and create value

### Implementation Notes

- CompanionWallet class: kintsugi/skills/intimate_ai/companion_wallet.py
- Needs: payment processing (Stripe), affiliate network integration,
  curated product database, shipping/fulfillment partnership
- The companion's gift_ideas() method uses memory of the human's
  interests to brainstorm — the BDI desires inform what to look for

### NOT for the demo — but this is the business model.
