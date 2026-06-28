# Twilio WhatsApp Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Meta WhatsApp Cloud API integration with a Twilio WhatsApp sandbox integration, so PRANA's WhatsApp bot works without requiring a Facebook account.

**Architecture:** Swap the outbound `MessageChannel` implementation (`WhatsAppChannel` → `TwilioWhatsAppChannel`, same protocol) and rewrite the inbound webhook's parsing/signature-verification to match Twilio's form-encoded payload and `X-Twilio-Signature` scheme instead of Meta's JSON+HMAC-SHA256 scheme. Settings, `.env.example`, and the Flutter confirmation screen are updated to match. This is a full swap — Meta-specific code is deleted, not flagged off.

**Tech Stack:** Python 3.9, FastAPI, httpx, the official `twilio` package (for `RequestValidator` only), pytest + respx for tests, Flutter/Dart for the mobile confirmation screen.

## Global Constraints

- Twilio sandbox numbers and the `From`/`To` fields they use are prefixed `whatsapp:` (e.g. `whatsapp:+14155238886`); the rest of the codebase (DB, `/register` API, `wa.me` link) stores bare E.164 numbers with no prefix. Normalization happens only at the edges of the Twilio-specific code (`TwilioWhatsAppChannel.send`, webhook's inbound parsing) — never change the DB schema or `/register` request/response shape to use the prefix.
- Twilio has no GET verify handshake — `GET /webhook/whatsapp` and `whatsapp_verify_token` are deleted entirely, not kept as dead code.
- Signature validation must use the official `twilio` package's `RequestValidator`, not hand-rolled HMAC — add `twilio` to `pyproject.toml`'s `dependencies` (not `requirements.txt`, which is unused by this project; `pyproject.toml` is authoritative per its `[project.dependencies]` and `[project.optional-dependencies.dev]` sections).
- `whatsapp_bot_number` (bare E.164, used only for the `wa.me` deep link in `prana/config.py` / `backend/main.py`) is unchanged — do not confuse it with the new `whatsapp_from_number` (Twilio-prefixed, used for the Twilio API).
- The activation handshake logic in `prana/bot/whatsapp_webhook.py` (unknown → register-first message; known-unverified → activate; verified → agent flow) must keep its existing behavior and regression tests passing unchanged in semantics — only the transport (JSON→form, signature scheme) changes.

---

### Task 1: Settings and env template

**Files:**
- Modify: `framework/config/settings.py`
- Modify: `.env.example`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `FrameworkSettings.whatsapp_account_sid: str`, `.whatsapp_auth_token: str`, `.whatsapp_from_number: str`, `.whatsapp_sandbox_join_code: str`, `.whatsapp_webhook_base_url: str` — consumed by Task 2 (`TwilioWhatsAppChannel`) and Task 3 (webhook signature validation).
- Removes: `FrameworkSettings.whatsapp_access_token`, `.whatsapp_phone_number_id`, `.whatsapp_app_secret`, `.whatsapp_verify_token` — no longer referenced anywhere after this plan completes.

- [ ] **Step 1: Update `FrameworkSettings`**

In `framework/config/settings.py`, replace these four lines:

```python
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_bot_number: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
```

with:

```python
    whatsapp_account_sid: str = ""
    whatsapp_auth_token: str = ""
    whatsapp_from_number: str = ""
    whatsapp_bot_number: str = ""
    whatsapp_sandbox_join_code: str = ""
    whatsapp_webhook_base_url: str = ""
```

(`whatsapp_bot_number` is kept, unchanged, in its existing position.)

- [ ] **Step 2: Update `.env.example`**

Replace the WhatsApp section:

```
# WhatsApp Business Cloud API / provider
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_BOT_NUMBER=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_APP_SECRET=
```

with:

```
# Twilio WhatsApp sandbox
# WHATSAPP_FROM_NUMBER includes the "whatsapp:" prefix (Twilio's sandbox number).
# WHATSAPP_BOT_NUMBER is the same number written as bare E.164, used only for
# the wa.me deep link shown to users (no prefix).
WHATSAPP_ACCOUNT_SID=
WHATSAPP_AUTH_TOKEN=
WHATSAPP_FROM_NUMBER=whatsapp:+14155238886
WHATSAPP_BOT_NUMBER=
WHATSAPP_SANDBOX_JOIN_CODE=
WHATSAPP_WEBHOOK_BASE_URL=
```

- [ ] **Step 3: Add `twilio` dependency**

In `pyproject.toml`, add `"twilio>=9"` to the `dependencies` list (after `"pydantic-settings>=2",`):

```toml
dependencies = [
    "numpy>=1.26.0",
    "pandas>=2.0.3",
    "requests>=2.31.0",
    "httpx>=0.27",
    "geopy>=2.4.0",
    "python-dotenv>=1.0.0",
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.1",
    "pydantic>=2",
    "pydantic-settings>=2",
    "twilio>=9",
]
```

- [ ] **Step 4: Install and verify**

Run: `pip install -e .`
Expected: installs successfully, `twilio` package importable.

Run: `python -c "from framework.config.settings import FrameworkSettings; s = FrameworkSettings(); print(s.whatsapp_from_number, s.whatsapp_sandbox_join_code)"`
Expected: prints two empty strings, no error.

- [ ] **Step 5: Commit**

```bash
git add framework/config/settings.py .env.example pyproject.toml
git commit -m "config: swap WhatsApp settings from Meta Cloud API to Twilio"
```

---

### Task 2: `TwilioWhatsAppChannel` (outbound)

**Files:**
- Modify: `framework/messaging/whatsapp.py`
- Modify: `tests/framework/messaging/test_whatsapp.py`

**Interfaces:**
- Consumes: `framework.messaging.base.OutboundMessage`, `DeliveryResult` (unchanged).
- Produces: `TwilioWhatsAppChannel(account_sid: str, auth_token: str, from_number: str, base_url: str = "https://api.twilio.com/2010-04-01", timeout: float = 30.0)` with `name = "whatsapp"` and `async def send(msg: OutboundMessage) -> DeliveryResult` — consumed by Task 6 (bootstrap wiring).

- [ ] **Step 1: Write the failing test**

Replace the entire contents of `tests/framework/messaging/test_whatsapp.py` with:

```python
import asyncio
import httpx
import respx
from framework.messaging.whatsapp import TwilioWhatsAppChannel
from framework.messaging.base import OutboundMessage


@respx.mock
def test_twilio_sends_and_parses_id():
    respx.post(
        "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
    ).mock(return_value=httpx.Response(200, json={"sid": "SM123"}))

    ch = TwilioWhatsAppChannel(
        account_sid="ACtest", auth_token="tok",
        from_number="whatsapp:+14155238886",
    )
    res = asyncio.run(ch.send(OutboundMessage(recipient="+919900", body="hi")))
    assert res.ok and res.provider_message_id == "SM123"


@respx.mock
def test_twilio_prefixes_bare_recipient():
    route = respx.post(
        "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
    ).mock(return_value=httpx.Response(200, json={"sid": "SM124"}))

    ch = TwilioWhatsAppChannel(
        account_sid="ACtest", auth_token="tok",
        from_number="whatsapp:+14155238886",
    )
    asyncio.run(ch.send(OutboundMessage(recipient="+919900", body="hi")))
    sent_body = route.calls[0].request.content.decode()
    assert "To=whatsapp%3A%2B919900" in sent_body


@respx.mock
def test_twilio_does_not_double_prefix_recipient():
    route = respx.post(
        "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
    ).mock(return_value=httpx.Response(200, json={"sid": "SM125"}))

    ch = TwilioWhatsAppChannel(
        account_sid="ACtest", auth_token="tok",
        from_number="whatsapp:+14155238886",
    )
    asyncio.run(
        ch.send(OutboundMessage(recipient="whatsapp:+919900", body="hi"))
    )
    sent_body = route.calls[0].request.content.decode()
    assert "To=whatsapp%3A%2B919900" in sent_body
    assert "whatsapp%3Awhatsapp" not in sent_body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/framework/messaging/test_whatsapp.py -v`
Expected: FAIL — `ImportError: cannot import name 'TwilioWhatsAppChannel'`

- [ ] **Step 3: Write the implementation**

Replace the entire contents of `framework/messaging/whatsapp.py` with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/framework/messaging/test_whatsapp.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add framework/messaging/whatsapp.py tests/framework/messaging/test_whatsapp.py
git commit -m "feat: replace Meta WhatsAppChannel with TwilioWhatsAppChannel"
```

---

### Task 3: Webhook inbound parsing and signature validation

**Files:**
- Modify: `prana/bot/whatsapp_webhook.py`
- Modify: `tests/prana/test_whatsapp_webhook.py`

**Interfaces:**
- Consumes: `framework.context.user.UserContext`, `framework.persistence.sqlite.SQLiteUserRepository` (via `build_repo()`), `prana.bot.bootstrap.{build_messaging, build_provider_chain, build_registry, build_repo, settings}` (unchanged), `framework.agent.agent` (as `make_agent`, unchanged), `twilio.request_validator.RequestValidator` (new).
- Produces: `POST /webhook/whatsapp` route behavior — used by Task 6 manual verification, no other task imports symbols from this file directly except tests.
- Removes: `GET /webhook/whatsapp` route, `_valid_signature`'s HMAC-SHA256 implementation, `_parse`'s JSON-nested-path implementation.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/prana/test_whatsapp_webhook.py` with:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator
from framework.ai.base import ChatResponse, ToolCall, Usage
from framework.ai.mock import MockProvider
from framework.context.user import UserContext
from framework.messaging.mock import MockChannel
from framework.messaging.registry import MessagingRegistry
from framework.persistence.memory import InMemoryUserRepository
from framework.tools.base import ToolRegistry
from prana.ai_tools.risk import risk_tool
import prana.bot.whatsapp_webhook as wh

BASE_URL = "https://example.ngrok-free.app/webhook/whatsapp"


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
    monkeypatch.setattr(wh, "AUTH_TOKEN", "secret")
    monkeypatch.setattr(wh, "validator", RequestValidator("secret"))
    monkeypatch.setattr(wh, "WEBHOOK_URL", BASE_URL)
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


def _sign(form: dict, secret: str) -> str:
    return RequestValidator(secret).compute_signature(BASE_URL, form)


def _post(c, form: dict):
    return c.post("/webhook/whatsapp", data=form,
                  headers={"X-Twilio-Signature": _sign(form, "secret")})


def test_known_user_gets_agent_reply(client):
    c, repo, channel = client
    import asyncio
    asyncio.run(
        repo.upsert(UserContext(user_id="u1", phone="+919900",
                                metadata={"lat": 13.08, "lon": 80.27, "verified": True})))
    r = _post(c, {"From": "whatsapp:+919900", "Body": "why is my risk high?"})
    assert r.status_code == 200
    assert channel.sent[-1].body == "Your risk is HIGH tonight."
    assert channel.sent[-1].recipient == "+919900"


def test_forged_signature_rejected(client):
    c, _, _ = client
    r = c.post("/webhook/whatsapp", data={"From": "whatsapp:+919900", "Body": "hi"},
               headers={"X-Twilio-Signature": "wrong"})
    assert r.status_code == 403


def test_unverified_user_first_message_activates(client):
    c, repo, channel = client
    import asyncio
    asyncio.run(
        repo.upsert(UserContext(user_id="u2", phone="+919900005555",
                                metadata={"lat": 13.08, "lon": 80.27, "verified": False})))
    r = _post(c, {"From": "whatsapp:+919900005555", "Body": "PRANA START"})
    assert r.status_code == 200
    assert "all set" in channel.sent[-1].body.lower()
    assert channel.sent[-1].recipient == "+919900005555"

    async def check():
        return await repo.get_by_phone("+919900005555")
    user = asyncio.run(check())
    assert user.metadata["verified"] is True


def test_verified_user_gets_normal_agent_flow_not_activation_message(client):
    c, repo, channel = client
    import asyncio
    asyncio.run(
        repo.upsert(UserContext(user_id="u3", phone="+919900006666",
                                metadata={"lat": 13.08, "lon": 80.27, "verified": True})))
    r = _post(c, {"From": "whatsapp:+919900006666", "Body": "why is my risk high?"})
    assert r.status_code == 200
    assert "all set" not in channel.sent[-1].body.lower()


def test_unknown_user_gets_register_first_message(client):
    c, repo, channel = client
    r = _post(c, {"From": "whatsapp:+919900007777", "Body": "hello"})
    assert r.status_code == 200
    assert "register" in channel.sent[-1].body.lower()


def test_inbound_whatsapp_prefix_is_stripped_for_lookup(client):
    c, repo, channel = client
    import asyncio
    asyncio.run(
        repo.upsert(UserContext(user_id="u4", phone="+919900008888",
                                metadata={"lat": 13.08, "lon": 80.27, "verified": True})))
    r = _post(c, {"From": "whatsapp:+919900008888", "Body": "why is my risk high?"})
    assert r.status_code == 200
    assert channel.sent[-1].recipient == "+919900008888"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/prana/test_whatsapp_webhook.py -v`
Expected: FAIL — `AttributeError: module 'prana.bot.whatsapp_webhook' has no attribute 'AUTH_TOKEN'` (or similar, since the module still has the old Meta-shaped names).

- [ ] **Step 3: Write the implementation**

Replace the entire contents of `prana/bot/whatsapp_webhook.py` with:

```python
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
```

(`_ONBOARD` text changed from "Reply START to set up..." to "Please register in the app first" to match the merged registration flow's intent — the bot can no longer onboard a user from a bare WhatsApp message since registration now requires the app. This matches `_ONBOARD`'s wording already used in the activation design doc.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/prana/test_whatsapp_webhook.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add prana/bot/whatsapp_webhook.py tests/prana/test_whatsapp_webhook.py
git commit -m "feat: switch WhatsApp webhook to Twilio form payloads and signature scheme"
```

---

### Task 4: Bootstrap wiring

**Files:**
- Modify: `prana/bot/bootstrap.py`

**Interfaces:**
- Consumes: `TwilioWhatsAppChannel` (Task 2), `FrameworkSettings.whatsapp_account_sid/.whatsapp_auth_token/.whatsapp_from_number` (Task 1).
- Produces: `build_messaging() -> MessagingRegistry` (signature unchanged) now registers a `TwilioWhatsAppChannel` instead of `WhatsAppChannel`.

- [ ] **Step 1: Update the import and construction**

In `prana/bot/bootstrap.py`, change:

```python
from framework.messaging.whatsapp import WhatsAppChannel
```

to:

```python
from framework.messaging.whatsapp import TwilioWhatsAppChannel
```

and change:

```python
def build_messaging() -> MessagingRegistry:
    reg = MessagingRegistry()
    reg.add(WhatsAppChannel(settings.whatsapp_access_token, settings.whatsapp_phone_number_id))
    return reg
```

to:

```python
def build_messaging() -> MessagingRegistry:
    reg = MessagingRegistry()
    reg.add(TwilioWhatsAppChannel(
        settings.whatsapp_account_sid, settings.whatsapp_auth_token, settings.whatsapp_from_number,
    ))
    return reg
```

- [ ] **Step 2: Verify nothing else imports the old name**

Run: `grep -rn "WhatsAppChannel\b" --include=*.py .` (use ripgrep/grep, not the old class name standalone)
Expected: only `TwilioWhatsAppChannel` references remain across `framework/`, `prana/`, `tests/`.

- [ ] **Step 3: Run the full backend test suite**

Run: `pytest tests/ -v`
Expected: all tests pass (this also re-validates Tasks 1-3 together with the rest of the suite, e.g. `tests/prana/test_register.py` which touches the same `UserContext`/repo code paths).

- [ ] **Step 4: Commit**

```bash
git add prana/bot/bootstrap.py
git commit -m "refactor: wire TwilioWhatsAppChannel into bot bootstrap"
```

---

### Task 5: `/register` response gains `sandbox_join_code`

**Files:**
- Modify: `backend/main.py`
- Modify: `tests/prana/test_register.py`

**Interfaces:**
- Consumes: `framework.config.settings.FrameworkSettings.whatsapp_sandbox_join_code` (Task 1).
- Produces: `RegisterResponse.sandbox_join_code: str` field — consumed by Task 6 (Flutter `RegisterResult`).

- [ ] **Step 1: Read the existing register test for the current pattern**

Run: `pytest tests/prana/test_register.py -v` (baseline — should currently pass)
Expected: all passing before this task's changes.

- [ ] **Step 2: Write the failing test**

Open `tests/prana/test_register.py` and add this test (matching the existing fixture/client pattern already in that file — use the same `client` fixture the other tests in the file use):

```python
def test_register_response_includes_sandbox_join_code(client, monkeypatch):
    import backend.main as main
    monkeypatch.setattr(main.settings, "whatsapp_sandbox_join_code", "able-tiger")
    response = client.post("/register", json={
        "phone": "+919900001234",
        "location_name": "Chennai",
        "lat": 13.08,
        "lon": 80.27,
        "urban_heat_offset": None,
        "onboarding": {"ac": False, "roof_material": "concrete", "floor_level": "ground"},
    })
    assert response.status_code == 200
    assert response.json()["sandbox_join_code"] == "able-tiger"
```

If the existing file's fixture is named differently or doesn't expose `client`/`monkeypatch` this way, match whatever pattern the other tests in `tests/prana/test_register.py` already use for posting to `/register` — read the file first and mirror its exact fixture name and JSON payload shape.

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/prana/test_register.py::test_register_response_includes_sandbox_join_code -v`
Expected: FAIL — `KeyError: 'sandbox_join_code'`

- [ ] **Step 4: Implement**

In `backend/main.py`, add the import:

```python
from prana.bot.bootstrap import settings  # noqa: E402
```

next to the existing `from prana.bot.bootstrap import build_repo, build_checkin_repo` line (combine into one import statement: `from prana.bot.bootstrap import build_repo, build_checkin_repo, settings`).

Update `RegisterResponse`:

```python
class RegisterResponse(BaseModel):
    ok: bool
    user_id: str
    verified: bool
    whatsapp_link: str
    sandbox_join_code: str
```

Update the `register` endpoint's return statement:

```python
    return RegisterResponse(
        ok=True, user_id=user.user_id, verified=was_verified, whatsapp_link=link,
        sandbox_join_code=settings.whatsapp_sandbox_join_code,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/prana/test_register.py -v`
Expected: all passed, including the new test.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/prana/test_register.py
git commit -m "feat: include Twilio sandbox join code in /register response"
```

---

### Task 6: Flutter onboarding screen — two-step WhatsApp activation

**Files:**
- Modify: `mobile_app/lib/models/user_registration.dart`
- Modify: `mobile_app/lib/screens/onboarding_screen.dart`
- Modify: `mobile_app/test/onboarding_screen_test.dart`

**Interfaces:**
- Consumes: `RegisterResponse.sandbox_join_code` (Task 5, as JSON field `sandbox_join_code`).
- Produces: `RegisterResult.sandboxJoinCode: String` — consumed only within `OnboardingScreen`.

- [ ] **Step 1: Read the existing widget test for the current pattern**

Run: `cd mobile_app && flutter test test/onboarding_screen_test.dart`
Expected: passes at baseline before changes.

- [ ] **Step 2: Write the failing test**

Add this test to `mobile_app/test/onboarding_screen_test.dart`, matching whatever mock `PranaApiClient`/widget-pumping pattern the existing tests in that file already use (read the file first to match the exact mock setup and `pumpWidget` call):

```dart
testWidgets('shows join code instructions after successful registration',
    (tester) async {
  // Reuse this test file's existing mock PranaApiClient setup, but have
  // register() return a RegisterResult with sandboxJoinCode: 'able-tiger'.
  // ... (fill in using the same mock/stub pattern as the file's existing
  // "shows Open WhatsApp button" style test, just additionally asserting:)
  expect(find.textContaining('able-tiger'), findsOneWidget);
});
```

(This step intentionally mirrors the file's existing successful-registration test scaffolding rather than introducing a new mocking approach — locate that existing test, copy its setup, and add the new assertion.)

- [ ] **Step 3: Run test to verify it fails**

Run: `cd mobile_app && flutter test test/onboarding_screen_test.dart`
Expected: FAIL — either a compile error (`sandboxJoinCode` undefined) or the new assertion failing to find the text.

- [ ] **Step 4: Update `RegisterResult`**

In `mobile_app/lib/models/user_registration.dart`, update the `RegisterResult` class:

```dart
class RegisterResult {
  RegisterResult({
    required this.ok,
    required this.userId,
    required this.verified,
    required this.whatsappLink,
    required this.sandboxJoinCode,
  });

  factory RegisterResult.fromJson(Map<String, dynamic> json) {
    return RegisterResult(
      ok: json['ok'] as bool,
      userId: json['user_id'] as String,
      verified: json['verified'] as bool,
      whatsappLink: json['whatsapp_link'] as String,
      sandboxJoinCode: json['sandbox_join_code'] as String,
    );
  }

  final bool ok;
  final String userId;
  final bool verified;
  final String whatsappLink;
  final String sandboxJoinCode;
}
```

- [ ] **Step 5: Update the confirmation card in `OnboardingScreen`**

In `mobile_app/lib/screens/onboarding_screen.dart`, replace the confirmation `Card` block:

```dart
              if (_result != null) ...[
                const SizedBox(height: 16),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('One more step'),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 10,
                          children: [
                            FilledButton(
                              onPressed: _openWhatsApp,
                              child: const Text('Open WhatsApp'),
                            ),
                            OutlinedButton(
                              onPressed: () =>
                                  widget.onContinue(_buildProfile(), _result?.userId),
                              child: const Text('Continue to Dashboard'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ],
```

with:

```dart
              if (_result != null) ...[
                const SizedBox(height: 16),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Two more steps to activate WhatsApp alerts'),
                        const SizedBox(height: 8),
                        Text(
                          "1. Send \"join ${_result!.sandboxJoinCode}\" to PRANA's "
                          'WhatsApp number',
                        ),
                        const SizedBox(height: 4),
                        const Text('2. Then tap below to finish activation'),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 10,
                          children: [
                            FilledButton(
                              onPressed: _openWhatsApp,
                              child: const Text('Open WhatsApp'),
                            ),
                            OutlinedButton(
                              onPressed: () =>
                                  widget.onContinue(_buildProfile(), _result?.userId),
                              child: const Text('Continue to Dashboard'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ],
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd mobile_app && flutter test test/onboarding_screen_test.dart`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add mobile_app/lib/models/user_registration.dart mobile_app/lib/screens/onboarding_screen.dart mobile_app/test/onboarding_screen_test.dart
git commit -m "feat: show two-step Twilio sandbox join instructions in onboarding screen"
```

---

### Task 7: End-to-end manual verification against the real Twilio sandbox

**Files:** None (no code changes — manual verification task).

**Interfaces:**
- Consumes: Real Twilio Account SID/Auth Token/sandbox number (provided by Gokul), an ngrok tunnel URL.

- [ ] **Step 1: Fill in `.env` with real values**

Set `WHATSAPP_ACCOUNT_SID`, `WHATSAPP_AUTH_TOKEN`, `WHATSAPP_FROM_NUMBER` (Twilio sandbox number with `whatsapp:` prefix), `WHATSAPP_BOT_NUMBER` (same number, bare), `WHATSAPP_SANDBOX_JOIN_CODE` (from the Twilio console's sandbox page), and `WHATSAPP_WEBHOOK_BASE_URL` (the ngrok HTTPS URL once running, e.g. `https://abc123.ngrok-free.app`) in `.env`.

- [ ] **Step 2: Start the tunnel and backend**

Run: `ngrok http 8000` (note the printed HTTPS URL, put it in `WHATSAPP_WEBHOOK_BASE_URL`)
Run: `uvicorn backend.main:app --reload`

- [ ] **Step 3: Configure Twilio sandbox webhook**

In the Twilio console's WhatsApp sandbox settings, set "WHEN A MESSAGE COMES IN" to `<ngrok-url>/webhook/whatsapp` (HTTP POST).

- [ ] **Step 4: Register a real phone via the API directly**

Run (replace `<phone>` with your real WhatsApp number in E.164, e.g. `+919900001234`):

```bash
curl -X POST http://127.0.0.1:8000/register -H "Content-Type: application/json" -d '{
  "phone": "<phone>", "location_name": "Test", "lat": 13.08, "lon": 80.27,
  "urban_heat_offset": null,
  "onboarding": {"ac": false, "roof_material": "concrete", "floor_level": "ground"}
}'
```

Expected: 200 response with `"verified": false` and a `sandbox_join_code` matching your `.env` value.

- [ ] **Step 5: Join the sandbox from your real phone**

From the WhatsApp account matching `<phone>`, send `join <sandbox_join_code>` to the Twilio sandbox number shown in the Twilio console.
Expected: Twilio replies confirming you've joined the sandbox.

- [ ] **Step 6: Send the activation message**

From the same WhatsApp account, send any message (e.g. "PRANA START").
Expected: you receive the `_ACTIVATED` reply ("You're all set!..."). Check the `uvicorn` server logs for no errors.

- [ ] **Step 7: Verify the agent flow**

Send a follow-up message like "why is my risk high?"
Expected: you receive a reply generated by the agent (requires `OPENROUTER_API_KEY`/`OLLAMA_MODEL` configured per existing LLM setup — not part of this plan's scope, but needed for this step to produce a non-error reply).

- [ ] **Step 8: Confirm no manual step is left undocumented**

If any step above required an undocumented workaround (e.g. a different webhook URL format Twilio actually expected, or a signature mismatch), note it back to Gokul before considering this task done — this is the final acceptance check for the whole plan.

---

## Self-Review

**Spec coverage:**
- §3 settings rename → Task 1. ✓
- §4 `TwilioWhatsAppChannel` → Task 2. ✓
- §5 inbound parsing/signature → Task 3. ✓
- Bootstrap wiring (implied by §4/§5 needing construction somewhere) → Task 4. ✓
- §6 registration flow / `sandbox_join_code` field + Flutter two-step copy → Tasks 5 and 6. ✓
- §7 `twilio` dependency → Task 1, Step 3. ✓
- §8 testing (messaging test rewrite, webhook test rewrite) → Tasks 2 and 3. ✓
- §9 risks (URL mismatch causing silent 403s, sandbox join happening outside the app) → addressed operationally in Task 7's manual verification, which is the only place these risks can actually be caught (signature math and sandbox state aren't unit-testable without a real Twilio account).

**Placeholder scan:** Task 6 Step 2 contains a deliberately partial test scaffold because the actual file's existing mock pattern wasn't read in this planning pass — flagging this explicitly rather than inventing a fake mock structure that might not match the file. The implementing engineer must read `mobile_app/test/onboarding_screen_test.dart` first (Task 6 Step 1 already directs this) and mirror its real pattern. This is the one acceptable exception to "no placeholders," since the alternative (guessing Dart mock syntax not yet seen) would likely be wrong and waste more time than reading the file.

**Type consistency:** `RegisterResponse.sandbox_join_code` (Task 5, Python/JSON) ↔ `RegisterResult.sandboxJoinCode` (Task 6, Dart) — names match through the `fromJson` mapping. `TwilioWhatsAppChannel(account_sid, auth_token, from_number, ...)` constructor signature in Task 2 matches the call in Task 4's `build_messaging()`. `settings.whatsapp_sandbox_join_code` (Task 1) matches its usage in Task 5.
