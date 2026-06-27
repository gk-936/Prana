import hashlib
import hmac
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from framework.ai.base import ChatResponse, ToolCall, Usage
from framework.ai.mock import MockProvider
from framework.context.user import UserContext
from framework.messaging.mock import MockChannel
from framework.messaging.registry import MessagingRegistry
from framework.persistence.memory import InMemoryUserRepository
from framework.tools.base import ToolRegistry
from prana.ai_tools.risk import risk_tool
import prana.bot.whatsapp_webhook as wh


@pytest.fixture
def client(monkeypatch):
    repo = InMemoryUserRepository()
    msg = MessagingRegistry(); mock_channel = MockChannel(); mock_channel.name = "whatsapp"; msg.add(mock_channel)
    reg = ToolRegistry(); reg.register(risk_tool)
    provider = MockProvider(responses=[
        ChatResponse(content=None, tool_calls=[ToolCall("1", "get_risk", {})], usage=Usage()),
        ChatResponse(content="Your risk is HIGH tonight.", usage=Usage()),
    ])
    monkeypatch.setattr(wh, "user_repo", repo)
    monkeypatch.setattr(wh, "messaging", msg)
    monkeypatch.setattr(wh, "registry", reg)
    monkeypatch.setattr(wh, "provider", provider)
    monkeypatch.setattr(wh, "APP_SECRET", "secret")
    monkeypatch.setattr(wh, "VERIFY_TOKEN", "verifytok")
    # patch the engine so get_risk doesn't hit network
    from unittest.mock import patch
    from datetime import datetime
    patcher = patch("prana.ai_tools.risk.PRANASystem")
    MockSys = patcher.start()
    MockSys.return_value.update_all.return_value = {
        "ccri": 72, "risk_level": "HIGH", "ndt": 34, "alert_message": "hot",
        "rds": {"rds_mid": 150, "consecutive_nights": 3}, "timestamp": datetime(2026, 6, 26),
    }
    app = FastAPI(); app.include_router(wh.router)
    yield TestClient(app), repo, mock_channel
    patcher.stop()


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_challenge(client):
    c, _, _ = client
    r = c.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "verifytok", "hub.challenge": "12345"})
    assert r.status_code == 200 and r.text == "12345"


def test_known_user_gets_agent_reply(client):
    c, repo, channel = client
    import asyncio
    asyncio.run(
        repo.upsert(UserContext(user_id="u1", phone="+919900",
                                metadata={"lat": 13.08, "lon": 80.27})))
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": "+919900", "text": {"body": "why is my risk high?"}}]}}]}]}).encode()
    r = c.post("/webhook/whatsapp", content=body,
               headers={"X-Hub-Signature-256": _sign(body, "secret")})
    assert r.status_code == 200
    assert channel.sent[-1].body == "Your risk is HIGH tonight."
    assert channel.sent[-1].recipient == "+919900"


def test_forged_signature_rejected(client):
    c, _, _ = client
    body = b'{"entry":[]}'
    r = c.post("/webhook/whatsapp", content=body,
               headers={"X-Hub-Signature-256": "sha256=wrong"})
    assert r.status_code == 403
