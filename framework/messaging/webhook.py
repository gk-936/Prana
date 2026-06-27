from __future__ import annotations

import httpx

from framework.messaging.base import DeliveryResult, OutboundMessage


class WebhookChannel:
    name = "webhook"

    def __init__(self, url: str, timeout: float = 15.0):
        self.url, self.timeout = url, timeout

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        payload = {"recipient": msg.recipient, "body": msg.body,
                   "template": msg.template, "data": msg.data}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.url, json=payload)
                resp.raise_for_status()
            return DeliveryResult(ok=True)
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc))
