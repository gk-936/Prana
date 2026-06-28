from __future__ import annotations

import httpx

from framework.messaging.base import DeliveryResult, OutboundMessage


class TwilioWhatsAppChannel:
    name = "whatsapp"

    def __init__(self, account_sid: str, auth_token: str, from_number: str,
                 base_url: str = "https://api.twilio.com/2010-04-01", timeout: float = 30.0):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        url = f"{self.base_url}/Accounts/{self.account_sid}/Messages.json"
        to = msg.recipient if msg.recipient.startswith("whatsapp:") else f"whatsapp:{msg.recipient}"
        data = {"From": self.from_number, "To": to, "Body": msg.body}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, data=data, auth=(self.account_sid, self.auth_token))
                resp.raise_for_status()
            sid = resp.json().get("sid")
            return DeliveryResult(ok=True, provider_message_id=sid)
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc))
