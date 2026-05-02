"""Concrete channel adapters for common platforms.

Each adapter wraps a platform-specific library and exposes the
unified ChannelAdapter interface. Add new platforms by subclassing
ChannelAdapter and registering with the dispatcher.

Dependencies are optional — each adapter gracefully degrades if
its library isn't installed.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from kintsugi.comms.base import ChannelAdapter, DeliveryReceipt

logger = logging.getLogger(__name__)


class WebhookAdapter(ChannelAdapter):
    """Send messages via HTTP webhooks (Slack-compatible, Discord, custom).

    Works with any service that accepts POST with a JSON body.
    No additional dependencies required.
    """

    def __init__(
        self,
        webhook_url: str,
        name: str = "webhook",
        body_template: dict[str, Any] | None = None,
    ) -> None:
        self._url = webhook_url
        self._name = name
        self._template = body_template or {"content": "{content}"}
        self._connected = bool(webhook_url)

    @property
    def channel_name(self) -> str:
        return self._name

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send(self, content: str, recipient: str,
                   metadata: dict[str, Any] | None = None) -> DeliveryReceipt:
        return await self.broadcast(content, metadata=metadata)

    async def broadcast(self, content: str, group: str | None = None,
                        metadata: dict[str, Any] | None = None) -> DeliveryReceipt:
        import urllib.request
        import urllib.error

        body = json.dumps(
            {k: v.replace("{content}", content) if isinstance(v, str) else v
             for k, v in self._template.items()}
        ).encode()

        req = urllib.request.Request(
            self._url, data=body,
            headers={"Content-Type": "application/json"},
        )

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=10),
            )
            return DeliveryReceipt(
                channel=self._name, success=True,
                recipient_count=1,
            )
        except Exception as e:
            return DeliveryReceipt(
                channel=self._name, success=False,
                error=str(e),
            )


class DiscordWebhookAdapter(WebhookAdapter):
    """Discord webhook adapter — uses Discord's webhook format."""

    def __init__(self, webhook_url: str) -> None:
        super().__init__(
            webhook_url=webhook_url,
            name="discord",
            body_template={"content": "{content}"},
        )


class SlackWebhookAdapter(WebhookAdapter):
    """Slack incoming webhook adapter."""

    def __init__(self, webhook_url: str) -> None:
        super().__init__(
            webhook_url=webhook_url,
            name="slack",
            body_template={"text": "{content}"},
        )


class TelegramAdapter(ChannelAdapter):
    """Telegram Bot API adapter.

    Requires: telegram bot token and chat_id for the target group.
    No additional Python packages — uses urllib directly.
    """

    def __init__(self, bot_token: str, default_chat_id: str = "") -> None:
        self._token = bot_token
        self._default_chat_id = default_chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._connected = bool(bot_token)

    @property
    def channel_name(self) -> str:
        return "telegram"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send(self, content: str, recipient: str,
                   metadata: dict[str, Any] | None = None) -> DeliveryReceipt:
        return await self._send_message(content, recipient)

    async def broadcast(self, content: str, group: str | None = None,
                        metadata: dict[str, Any] | None = None) -> DeliveryReceipt:
        chat_id = group or self._default_chat_id
        if not chat_id:
            return DeliveryReceipt(
                channel="telegram", success=False,
                error="No chat_id specified",
            )
        return await self._send_message(content, chat_id)

    async def _send_message(self, text: str, chat_id: str) -> DeliveryReceipt:
        import urllib.request
        import urllib.error

        url = f"{self._base_url}/sendMessage"
        body = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }).encode()

        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
        )

        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=10),
            )
            data = json.loads(resp.read())
            return DeliveryReceipt(
                channel="telegram", success=data.get("ok", False),
                recipient_count=1,
                message_id=str(data.get("result", {}).get("message_id", "")),
            )
        except Exception as e:
            return DeliveryReceipt(
                channel="telegram", success=False,
                error=str(e),
            )


class LogAdapter(ChannelAdapter):
    """Log-only adapter for testing and audit. Writes to Python logger."""

    def __init__(self, name: str = "log") -> None:
        self._name = name

    @property
    def channel_name(self) -> str:
        return self._name

    @property
    def is_connected(self) -> bool:
        return True

    async def send(self, content: str, recipient: str,
                   metadata: dict[str, Any] | None = None) -> DeliveryReceipt:
        logger.info("[%s → %s] %s", self._name, recipient, content[:200])
        return DeliveryReceipt(
            channel=self._name, success=True, recipient_count=1,
        )

    async def broadcast(self, content: str, group: str | None = None,
                        metadata: dict[str, Any] | None = None) -> DeliveryReceipt:
        logger.info("[%s broadcast] %s", self._name, content[:200])
        return DeliveryReceipt(
            channel=self._name, success=True, recipient_count=1,
        )
