from __future__ import annotations

import httpx

from framework.messaging.base import DeliveryResult, OutboundMessage


class WhatsAppChannel:
    name = "whatsapp"

    def __init__(self, access_token: str, phone_number_id: str,
                 base_url: str = "https://graph.facebook.com/v20.0", timeout: float = 30.0):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": msg.recipient,
            "type": "text",
            "text": {"body": msg.body},
        }
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
            mid = (resp.json().get("messages") or [{}])[0].get("id")
            return DeliveryResult(ok=True, provider_message_id=mid)
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc))
