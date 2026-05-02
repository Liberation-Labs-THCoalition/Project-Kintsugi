"""Unified communications dispatcher.

Routes messages to one or many channels simultaneously. Supports
normal, urgent, and crisis-mode delivery with different rate
limiting and retry behavior.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

from kintsugi.comms.base import ChannelAdapter, DeliveryReceipt

logger = logging.getLogger(__name__)


class Urgency(IntEnum):
    LOW = 1       # Informational, can wait
    NORMAL = 2    # Standard notification
    HIGH = 3      # Time-sensitive, deliver promptly
    CRITICAL = 4  # Crisis — bypass rate limits, all channels


@dataclass
class Message:
    """A message to be dispatched across channels."""
    content: str
    urgency: Urgency = Urgency.NORMAL
    title: str = ""
    sender: str = "Kintsugi"
    recipients: list[str] | None = None  # None = broadcast to all
    group: str | None = None  # Target group/channel within platform
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class DeliveryResult:
    """Result of dispatching a message across channels."""
    message: Message
    receipts: list[DeliveryReceipt] = field(default_factory=list)
    dispatched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.receipts)

    @property
    def any_succeeded(self) -> bool:
        return any(r.success for r in self.receipts)

    @property
    def total_recipients(self) -> int:
        return sum(r.recipient_count for r in self.receipts)

    @property
    def failed_channels(self) -> list[str]:
        return [r.channel for r in self.receipts if not r.success]

    def summary(self) -> str:
        ok = sum(1 for r in self.receipts if r.success)
        total = len(self.receipts)
        recipients = self.total_recipients
        return (
            f"Dispatched to {ok}/{total} channels, "
            f"{recipients} recipients reached"
        )


class CommsDispatcher:
    """Routes messages to registered channel adapters.

    Supports:
    - Single-channel send (to a specific adapter)
    - Multi-channel broadcast (fan-out to all or selected adapters)
    - Crisis mode (bypass rate limits, parallel dispatch, retry)
    - Audit trail (every dispatch logged)
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}
        self._dispatch_log: list[DeliveryResult] = []

    def register(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter."""
        self._adapters[adapter.channel_name] = adapter
        logger.info("Registered comms channel: %s", adapter.channel_name)

    def unregister(self, channel_name: str) -> None:
        """Remove a channel adapter."""
        self._adapters.pop(channel_name, None)

    @property
    def channels(self) -> list[str]:
        """List of registered channel names."""
        return list(self._adapters.keys())

    @property
    def connected_channels(self) -> list[str]:
        """List of channels that are connected and ready."""
        return [name for name, adapter in self._adapters.items()
                if adapter.is_connected]

    async def send(
        self,
        message: Message,
        channel: str,
    ) -> DeliveryResult:
        """Send a message to a single channel."""
        result = DeliveryResult(message=message)

        adapter = self._adapters.get(channel)
        if adapter is None:
            result.receipts.append(DeliveryReceipt(
                channel=channel, success=False,
                error=f"Channel '{channel}' not registered",
            ))
            return result

        try:
            if message.recipients:
                for recipient in message.recipients:
                    receipt = await adapter.send(
                        content=self._format_message(message),
                        recipient=recipient,
                        metadata=message.metadata,
                    )
                    result.receipts.append(receipt)
            else:
                receipt = await adapter.broadcast(
                    content=self._format_message(message),
                    group=message.group,
                    metadata=message.metadata,
                )
                result.receipts.append(receipt)
        except Exception as e:
            result.receipts.append(DeliveryReceipt(
                channel=channel, success=False,
                error=str(e),
            ))

        self._dispatch_log.append(result)
        return result

    async def broadcast(
        self,
        message: Message,
        channels: list[str] | None = None,
    ) -> DeliveryResult:
        """Broadcast a message to multiple channels simultaneously.

        Args:
            message: The message to send.
            channels: List of channel names. None = all registered.
                For CRITICAL urgency, always uses all channels.
        """
        result = DeliveryResult(message=message)

        if message.urgency == Urgency.CRITICAL:
            targets = list(self._adapters.keys())
        elif channels:
            targets = [c for c in channels if c in self._adapters]
        else:
            targets = list(self._adapters.keys())

        if not targets:
            logger.warning("No channels available for broadcast")
            return result

        # Parallel dispatch for CRITICAL/HIGH, sequential for others
        if message.urgency >= Urgency.HIGH:
            tasks = [
                self._dispatch_to_channel(message, channel)
                for channel in targets
            ]
            receipts = await asyncio.gather(*tasks, return_exceptions=True)
            for receipt in receipts:
                if isinstance(receipt, DeliveryReceipt):
                    result.receipts.append(receipt)
                elif isinstance(receipt, Exception):
                    result.receipts.append(DeliveryReceipt(
                        channel="unknown", success=False,
                        error=str(receipt),
                    ))
        else:
            for channel in targets:
                receipt = await self._dispatch_to_channel(message, channel)
                result.receipts.append(receipt)

        self._dispatch_log.append(result)
        logger.info("Broadcast: %s", result.summary())
        return result

    async def crisis_alert(
        self,
        content: str,
        title: str = "CRISIS ALERT",
    ) -> DeliveryResult:
        """Emergency broadcast to ALL channels with CRITICAL urgency.

        Convenience method for crisis response scenarios.
        """
        message = Message(
            content=content,
            title=title,
            urgency=Urgency.CRITICAL,
            sender="Kintsugi Crisis Response",
            metadata={"crisis": True},
        )
        return await self.broadcast(message)

    async def morning_briefing(
        self,
        briefing_text: str,
        channels: list[str] | None = None,
    ) -> DeliveryResult:
        """Send the dreamer's morning briefing to specified channels."""
        message = Message(
            content=briefing_text,
            title="Morning Briefing",
            urgency=Urgency.LOW,
            sender="Kintsugi Dreamer",
        )
        return await self.broadcast(message, channels=channels)

    def get_dispatch_log(
        self, limit: int = 50
    ) -> list[DeliveryResult]:
        """Return recent dispatch history for audit."""
        return self._dispatch_log[-limit:]

    async def _dispatch_to_channel(
        self, message: Message, channel: str
    ) -> DeliveryReceipt:
        """Dispatch to a single channel with error handling."""
        adapter = self._adapters.get(channel)
        if adapter is None:
            return DeliveryReceipt(
                channel=channel, success=False,
                error=f"Channel '{channel}' not registered",
            )

        try:
            return await adapter.broadcast(
                content=self._format_message(message),
                group=message.group,
                metadata=message.metadata,
            )
        except Exception as e:
            logger.error("Dispatch to %s failed: %s", channel, e)
            return DeliveryReceipt(
                channel=channel, success=False,
                error=str(e),
            )

    @staticmethod
    def _format_message(message: Message) -> str:
        """Format a message for delivery."""
        parts = []
        if message.urgency >= Urgency.CRITICAL:
            parts.append(f"🚨 {message.title or 'URGENT'}")
        elif message.title:
            parts.append(message.title)
        parts.append(message.content)
        return "\n\n".join(parts)
