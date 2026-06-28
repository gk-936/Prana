# Twilio WhatsApp Channel — Design Spec

**Date:** 2026-06-28
**Status:** Approved
**Author:** Gokul + Claude (brainstorming session)

## 1. Goal & Scope

Replace the Meta WhatsApp Cloud API integration with Twilio's WhatsApp
sandbox. Meta's developer platform requires a Facebook account, which Gokul
does not have; Twilio's signup only needs an email and offers a free sandbox
mode for development.

This is a full swap, not a dual-provider setup: Meta-specific code
(`GET /webhook/whatsapp` verify handshake, raw-body HMAC-SHA256 signature
check, `graph.facebook.com` outbound calls) is deleted, not kept behind a
flag. If Meta access becomes available later, that is a separate future
change.

Out of scope:

- Supporting Meta and Twilio simultaneously via a provider switch.
- Twilio production (non-sandbox) WhatsApp sender approval — sandbox only.
- Any change to the `/register` API contract beyond adding one field
  (`sandbox_join_code`) to the response.
- Any change to the agent flow, tool registry, or risk-calculation logic.

## 2. Background: Why This Isn't a Drop-In Replacement

Twilio's webhook/signature scheme differs structurally from Meta's:

- **Payload shape:** Meta sends JSON (`entry[0].changes[0].value.messages[0]`).
  Twilio sends `application/x-www-form-urlencoded` with flat fields
  (`From`, `Body`, etc.).
- **Phone format:** Twilio prefixes numbers with `whatsapp:` (e.g.
  `whatsapp:+14155551234`) in both the inbound `From` field and the address
  you send to. The rest of the codebase (DB schema, `/register` API, the
  `wa.me` deep link) stores bare E.164 numbers with no prefix.
- **Signature scheme:** Meta uses HMAC-SHA256 over the raw request body,
  sent as `X-Hub-Signature-256`. Twilio uses HMAC-SHA1 over the full
  callback URL concatenated with sorted POST params, base64-encoded, sent as
  `X-Twilio-Signature`. This requires knowing the exact public URL Twilio
  called — which depends on what's in front of the app (ngrok, proxy
  headers) and can't be reliably reconstructed from the incoming request
  alone behind a tunnel.
- **No verify handshake:** Meta's `GET /webhook/whatsapp` challenge-response
  endpoint has no Twilio equivalent.
- **Sandbox join step:** Before Twilio will deliver any message to/from a
  user, that user must first WhatsApp a join code (e.g. `join able-tiger`)
  to the sandbox number. This happens entirely on Twilio's side, before the
  webhook ever sees a message — it sits in front of, not instead of, the
  existing "any inbound message activates" handshake the webhook already
  does (per `docs/superpowers/specs/2026-06-27-whatsapp-registration-design.md`).

## 3. Settings (`framework/config/settings.py`)

Remove:

- `whatsapp_access_token`
- `whatsapp_phone_number_id`
- `whatsapp_app_secret`
- `whatsapp_verify_token` (no Twilio equivalent — no GET handshake)

Add:

- `whatsapp_account_sid: str = ""` — Twilio Account SID
- `whatsapp_auth_token: str = ""` — Twilio Auth Token (used both for REST
  auth and signature validation)
- `whatsapp_from_number: str = ""` — sandbox number, e.g.
  `whatsapp:+14155238886` (stored with the prefix already present, since
  this is Twilio-specific config, not a user-facing phone)
- `whatsapp_sandbox_join_code: str = ""` — e.g. `able-tiger`; not secret,
  shown directly to users
- `whatsapp_webhook_base_url: str = ""` — e.g. the current ngrok URL; used
  to build the exact callback URL for signature validation instead of
  trusting `Request.url`

Keep unchanged:

- `whatsapp_bot_number` — bare E.164, still used only to build the `wa.me`
  deep link shown to users (this is the user-facing sandbox number written
  as a normal phone number for the link, distinct from
  `whatsapp_from_number`'s Twilio-prefixed form used for the API)

`.env.example` updated to match (remove the four retired vars, add the five
new ones, with a comment that `WHATSAPP_FROM_NUMBER` includes the
`whatsapp:` prefix while `WHATSAPP_BOT_NUMBER` does not).

## 4. Outbound: `TwilioWhatsAppChannel`

Replaces `WhatsAppChannel` in `framework/messaging/whatsapp.py`. Same
`MessageChannel` protocol (`name = "whatsapp"`,
`async def send(msg: OutboundMessage) -> DeliveryResult`), so
`MessagingRegistry` and `prana/bot/bootstrap.py`'s `build_messaging()` need
only a constructor-args change, not a structural one.

```python
class TwilioWhatsAppChannel:
    name = "whatsapp"

    def __init__(self, account_sid: str, auth_token: str, from_number: str,
                 base_url: str = "https://api.twilio.com/2010-04-01",
                 timeout: float = 30.0):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number  # already whatsapp:-prefixed
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        url = f"{self.base_url}/Accounts/{self.account_sid}/Messages.json"
        to = msg.recipient if msg.recipient.startswith("whatsapp:") \
            else f"whatsapp:{msg.recipient}"
        data = {"From": self.from_number, "To": to, "Body": msg.body}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url, data=data, auth=(self.account_sid, self.auth_token))
                resp.raise_for_status()
            sid = resp.json().get("sid")
            return DeliveryResult(ok=True, provider_message_id=sid)
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc))
```

Uses `httpx` directly (consistent with the existing pattern) rather than the
`twilio` package's REST client, since the call is a single simple POST.

## 5. Inbound: `prana/bot/whatsapp_webhook.py`

- `GET /webhook/whatsapp` is deleted entirely (no Twilio equivalent).
- `POST /webhook/whatsapp` reads `await request.form()` instead of parsing
  JSON. Extracts `From` and `Body`. Strips a leading `whatsapp:` from `From`
  before any repo lookup, so the rest of the function operates on the same
  bare E.164 string the DB/`/register` API already use.
- Signature validation uses the official `twilio` package's
  `RequestValidator`:

```python
from twilio.request_validator import RequestValidator

validator = RequestValidator(settings.whatsapp_auth_token)

def _valid_signature(form: dict, header: str | None) -> bool:
    if not header:
        return False
    url = f"{settings.whatsapp_webhook_base_url}/webhook/whatsapp"
    return validator.validate(url, form, header)
```

- The existing three-way branch (unknown phone → "register first" message;
  known-but-unverified → flip `verified=True` + activation reply; verified
  → agent flow) is unchanged in logic, operating on the normalized phone.
- `_parse` is simplified since Twilio's form fields are flat — no nested
  `entry[].changes[].value.messages[]` traversal needed. A malformed/missing
  `From` or `Body` still acks with 200 and does nothing, matching today's
  "ignore status callbacks" behavior.

## 6. Registration Flow Changes

- `backend/main.py`'s `/register` endpoint logic is unchanged — still bare
  E.164 in, still builds the `wa.me` link from `WHATSAPP_BOT_NUMBER`.
- `RegisterResponse` gains one field: `sandbox_join_code: str`, populated
  from `settings.whatsapp_sandbox_join_code`. This lets the Flutter app show
  the join code without needing its own copy of that config.
- Flutter `OnboardingScreen` confirmation card is updated to two-step copy:
  1. "Send `join {sandbox_join_code}` to {bot_number}" — plain text
     instruction (not a deep link, since the user needs to type/send that
     exact text and Twilio's sandbox join is a one-time per-number step).
  2. Existing "Open WhatsApp" button using the existing `wa.me` deep link
     (still sends `PRANA START`), which completes the existing
     unverified→verified activation handshake once Twilio is actually
     delivering messages.

## 7. Dependencies

Add `twilio` to `requirements.txt` — used only for `RequestValidator`.

## 8. Testing

### 8.1 `tests/framework/messaging/test_whatsapp.py`

Rewritten for `TwilioWhatsAppChannel`:

- Mock `https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json`,
  assert `send()` returns `ok=True` with the Twilio `sid` as
  `provider_message_id`.
- Assert the POST body's `To` field gets `whatsapp:` prefixed when the
  recipient is passed bare, and is left alone if already prefixed.

### 8.2 `tests/prana/test_whatsapp_webhook.py`

Rewritten:

- `test_verify_challenge` deleted (no GET handshake in Twilio).
- All test bodies become form-encoded dicts with `From`/`Body` keys instead
  of the nested JSON shape; `From` values use the `whatsapp:+91...` prefix
  to exercise stripping.
- Signature test helper replaced with one that builds a Twilio-style
  signature (or directly uses `RequestValidator` to compute the expected
  header) over `(base_url + path, form_params)`.
- `test_forged_signature_rejected` continues to assert 403 on a bad
  signature.
- `test_known_user_gets_agent_reply`,
  `test_unverified_user_first_message_activates`, and
  `test_verified_user_gets_normal_agent_flow_not_activation_message` are
  preserved with the same assertions, just driven through form-encoded
  bodies — these are the regression checks for the activation handshake
  from the prior WhatsApp-registration work and must keep passing unchanged
  in behavior.
- New test: inbound `From` with `whatsapp:` prefix resolves to the same
  repo row as a bare-stored phone (explicit normalization check).

## 9. Risks / Things to Get Right

- Signature validation will silently 403 everything if
  `whatsapp_webhook_base_url` doesn't exactly match what Twilio computes
  (trailing slash, http vs https, wrong path) — this is the most likely
  source of "it just doesn't work" during setup, worth calling out in setup
  instructions/error logging.
- The Twilio sandbox join step happens entirely outside this codebase
  (directly between the user's WhatsApp client and Twilio). If a user skips
  it, their inbound messages never reach the webhook at all — there's no
  way to detect or message that user, since the system never receives
  anything from them. This is a sandbox-specific limitation that goes away
  with a production Twilio WhatsApp sender (out of scope here).

Related: [[2026-06-27-whatsapp-registration-design]]
