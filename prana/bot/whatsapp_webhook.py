"""Twilio WhatsApp webhook: message -> agent -> reply."""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from twilio.request_validator import RequestValidator

from framework import agent as make_agent
from prana.bot.bootstrap import (
    build_messaging, build_provider_chain, build_registry, build_repo, settings,
)

router = APIRouter()

# Module-level singletons (tests monkeypatch these)
registry = build_registry()
messaging = build_messaging()
user_repo = build_repo()
provider = build_provider_chain()
AUTH_TOKEN = settings.whatsapp_auth_token
WEBHOOK_URL = f"{settings.whatsapp_webhook_base_url}/webhook/whatsapp"
validator = RequestValidator(AUTH_TOKEN)

_ONBOARD = "Welcome to PRANA. Please register in the app first."
_ACTIVATED = "You're all set! PRANA will alert you when conditions turn risky."


def _valid_signature(form: dict, header: str | None) -> bool:
    if not header:
        return False
    return validator.validate(WEBHOOK_URL, form, header)


def _parse(form: dict):
    phone = form.get("From")
    body = form.get("Body")
    if not phone or body is None:
        return None
    return phone.removeprefix("whatsapp:"), body


@router.post("/webhook/whatsapp")
async def receive(request: Request) -> Response:
    form = dict(await request.form())
    if not _valid_signature(form, request.headers.get("X-Twilio-Signature")):
        return Response(status_code=403)

    parsed = _parse(form)
    if not parsed:
        return Response(status_code=200)
    phone, text = parsed

    user = await user_repo.get_by_phone(phone)
    if user is None:
        await messaging.send(channel="whatsapp", recipient=phone, body=_ONBOARD)
        return Response(status_code=200)

    if not user.metadata.get("verified", True):
        user.metadata["verified"] = True
        await user_repo.upsert(user)
        await messaging.send(channel="whatsapp", recipient=phone, body=_ACTIVATED)
        return Response(status_code=200)

    ag = make_agent(provider, registry, max_steps=settings.agent_max_steps,
                    temperature=settings.agent_temperature)
    result = await ag.run(text, user)
    await messaging.send(channel="whatsapp", recipient=phone,
                          body=result.answer or "Sorry, please try again.")
    return Response(status_code=200)
