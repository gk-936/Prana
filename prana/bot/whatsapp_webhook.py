"""WhatsApp Cloud API webhook: message -> agent -> reply."""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, Request, Response

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
APP_SECRET = settings.whatsapp_app_secret
VERIFY_TOKEN = settings.whatsapp_verify_token

_ONBOARD = "Welcome to PRANA. Reply START to set up heat alerts for your area."
_ACTIVATED = "You're all set! PRANA will alert you when conditions turn risky."


@router.get("/webhook/whatsapp")
async def verify(request: Request) -> Response:
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


def _valid_signature(body: bytes, header: str | None) -> bool:
    if not header or not APP_SECRET:
        return False
    expected = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def _parse(payload: dict):
    try:
        msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        return msg["from"], msg["text"]["body"]
    except (KeyError, IndexError, TypeError):
        return None


@router.post("/webhook/whatsapp")
async def receive(request: Request) -> Response:
    body = await request.body()
    if not _valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=403)

    parsed = _parse(json.loads(body))
    if not parsed:
        return Response(status_code=200)  # status callbacks etc. — ack and ignore
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
