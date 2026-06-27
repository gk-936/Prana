from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from framework.messaging.base import DeliveryResult, OutboundMessage


class EmailChannel:
    name = "email"

    def __init__(self, host: str, port: int, user: str, password: str, sender: str):
        self.host, self.port = host, port
        self.user, self.password, self.sender = user, password, sender

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        def _send() -> DeliveryResult:
            em = EmailMessage()
            em["From"], em["To"] = self.sender, msg.recipient
            em["Subject"] = msg.template or "Notification"
            em.set_content(msg.body)
            with smtplib.SMTP(self.host, self.port) as s:
                s.starttls()
                if self.user:
                    s.login(self.user, self.password)
                s.send_message(em)
            return DeliveryResult(ok=True)
        try:
            return await asyncio.to_thread(_send)
        except Exception as exc:  # noqa: BLE001
            return DeliveryResult(ok=False, error=str(exc))
