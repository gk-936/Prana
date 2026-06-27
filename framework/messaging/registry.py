from __future__ import annotations

from framework.errors import MessagingError
from framework.messaging.base import DeliveryResult, MessageChannel, OutboundMessage


class MessagingRegistry:
    def __init__(self) -> None:
        self._channels: dict[str, MessageChannel] = {}

    def add(self, channel: MessageChannel) -> None:
        self._channels[channel.name] = channel

    async def send(self, *, channel: str, recipient: str, body: str,
                   template: str | None = None, data: dict | None = None) -> DeliveryResult:
        if channel not in self._channels:
            raise MessagingError(f"Unknown channel '{channel}'")
        msg = OutboundMessage(recipient=recipient, body=body, template=template, data=data or {})
        return await self._channels[channel].send(msg)
