"""Unified communications suite for multi-channel outreach.

Provides a single dispatch interface for reaching people across
Discord, Telegram, Signal, SMS, Email, and webhooks. Designed for
crisis response but used by all skill chips that need to notify.

Usage:
    dispatcher = CommsDispatcher()
    dispatcher.register(DiscordAdapter(token=...))
    dispatcher.register(TelegramAdapter(token=...))

    await dispatcher.broadcast(
        Message(content="Flood warning — shelter at community center",
                urgency=Urgency.CRITICAL),
        channels=["discord", "telegram", "sms"],
    )
"""
from kintsugi.comms.dispatcher import (
    CommsDispatcher,
    Message,
    Urgency,
    DeliveryResult,
)
from kintsugi.comms.base import ChannelAdapter
