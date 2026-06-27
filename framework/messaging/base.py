from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class OutboundMessage:
    recipient: str
    body: str
    template: str | None = None
    data: dict = field(default_factory=dict)


@dataclass
class DeliveryResult:
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None


@runtime_checkable
class MessageChannel(Protocol):
    name: str

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        ...
