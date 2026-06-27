from __future__ import annotations

from framework.messaging.base import DeliveryResult, OutboundMessage


class MockChannel:
    name = "mock"

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        self.sent.append(msg)
        return DeliveryResult(ok=True, provider_message_id=f"mock-{len(self.sent)}")
