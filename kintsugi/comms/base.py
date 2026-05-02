"""Base adapter interface for communication channels."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class DeliveryReceipt:
    """Confirmation that a message was delivered to a channel."""
    channel: str
    success: bool
    recipient_count: int = 0
    message_id: str = ""
    error: str = ""
    metadata: dict[str, Any] | None = None


class ChannelAdapter(ABC):
    """Base class for communication channel adapters.

    Each adapter handles one platform (Discord, Telegram, etc.)
    and implements send + broadcast.
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Unique name for this channel (e.g., 'discord', 'telegram')."""
        ...

    @property
    def is_connected(self) -> bool:
        """Whether the adapter has valid credentials and is ready."""
        return False

    @abstractmethod
    async def send(
        self,
        content: str,
        recipient: str,
        metadata: dict[str, Any] | None = None,
    ) -> DeliveryReceipt:
        """Send a message to a specific recipient."""
        ...

    @abstractmethod
    async def broadcast(
        self,
        content: str,
        group: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DeliveryReceipt:
        """Broadcast a message to a group or all subscribers."""
        ...

    async def connect(self) -> None:
        """Initialize the connection (called once at startup)."""
        pass

    async def disconnect(self) -> None:
        """Clean up the connection."""
        pass
