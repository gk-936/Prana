# WhatsApp Registration — Design Spec

**Date:** 2026-06-27
**Status:** Approved
**Author:** Gokul + Claude (brainstorming session)

## 1. Goal & Scope

Let a PRANA user register their phone number, location, and home profile from
the Flutter app, so the WhatsApp bot (built in the AI framework work) can
actually send them alerts. Today the webhook can only reply to phones that
already exist in the `users` table — nothing writes to that table, so no real
user can ever receive a WhatsApp message.

### Driving flow

```
Flutter app: user fills phone + location + home profile -> taps Register
  -> POST /register -> SQLiteUserRepository.upsert (verified=false)
  -> app shows "Open WhatsApp to activate" deep link
  -> user taps it, sends the prefilled WhatsApp message
  -> webhook sees a known-but-unverified phone, flips verified=true,
     replies with a welcome message
  -> from then on, that phone gets the normal agent flow (e.g. get_risk
     explanations) on every inbound message
```

### Chosen parameters

- **Registration fields:** phone, location (GPS lat/lon + name), home profile
  (AC: bool, roof_material, floor_level) — feeds directly into
  `RDSCalculator.onboarding_data`.
- **Verification:** WhatsApp opt-in, not OTP. The app never sends a WhatsApp
  message itself; it only shows a `wa.me` deep link with a prefilled message.
  The user's own outbound message is what completes verification (Meta
  requires user-initiated contact before a business can message freely).
- **Activation trigger:** ANY inbound message from a known-but-unverified
  phone completes verification (not just an exact "PRANA START" string) —
  this keeps the prefilled text non-critical and still satisfies "user
  initiated."
- **Endpoint home:** `POST /register` added to the existing `backend/main.py`
  FastAPI app, writing through the framework's `SQLiteUserRepository`
  (same DB the webhook reads — one source of truth).
- **`verified` state:** stored in `UserContext.metadata["verified"]` (bool),
  not as a first-class field on the generic `UserContext` model — keeps the
  framework's `UserContext` free of PRANA-specific concepts.
- **Flutter:** refactor the existing single-file `main.dart` (431 lines, a
  working risk dashboard with GPS + manual lat/lon/heat-offset fields and a
  `POST /risk/current` call) into `models/`, `services/`, `screens/`, adding
  a new onboarding screen. The dashboard's existing behavior is preserved
  unchanged, just relocated.

## 2. Backend Changes

### 2.1 `SQLiteUserRepository` schema migration

`framework/persistence/sqlite.py` currently creates:

```sql
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    phone TEXT,
    location_name TEXT,
    lat REAL,
    lon REAL,
    urban_heat_offset REAL,
    onboarding_json TEXT,
    role TEXT,
    locale TEXT,
    created_at TEXT
)
```

Add a `verified INTEGER DEFAULT 0` column. Because this is
`CREATE TABLE IF NOT EXISTS`, a pre-existing database file from before this
change will NOT get the new column automatically. Guard with a one-time
`ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0` wrapped in a
try/except (SQLite raises `OperationalError` if the column already exists;
catching and ignoring that specific case is the only safe way to make this
idempotent), run once in `__init__` right after `CREATE TABLE`.

`_to_user` reads the column into `UserContext.metadata["verified"]` (`bool`,
defaulting `False` if the column is absent/NULL). `_upsert` writes
`1 if metadata.get("verified") else 0`.

`InMemoryUserRepository` needs no change — it stores the whole `UserContext`
object, so `metadata["verified"]` round-trips automatically.

### 2.2 `POST /register` — `backend/main.py`

```python
class HomeProfile(BaseModel):
    ac: bool
    roof_material: str   # "concrete" | "tin" | "other"
    floor_level: str     # "ground" | "middle" | "top"

class RegisterRequest(BaseModel):
    phone: str = Field(..., min_length=8, max_length=20)
    location_name: str = Field(..., min_length=1, max_length=120)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    urban_heat_offset: Optional[float] = Field(None, ge=0, le=8)
    onboarding: HomeProfile

class RegisterResponse(BaseModel):
    ok: bool
    user_id: str
    verified: bool
    whatsapp_link: str

@app.post("/register", response_model=RegisterResponse)
async def register(payload: RegisterRequest) -> RegisterResponse:
    user = UserContext(
        user_id=payload.phone,
        phone=payload.phone,
        metadata={
            "lat": payload.lat,
            "lon": payload.lon,
            "location_name": payload.location_name,
            "urban_heat_offset": payload.urban_heat_offset,
            "onboarding": payload.onboarding.model_dump(),
            "verified": False,
        },
    )
    await user_repo.upsert(user)
    link = f"https://wa.me/{WHATSAPP_BOT_NUMBER}?text=PRANA%20START"
    return RegisterResponse(
        ok=True, user_id=user.user_id, verified=False, whatsapp_link=link
    )
```

`user_id = phone` — phone is the natural key; the webhook already looks users
up by phone, so this keeps lookups trivial (`get_by_phone` and `get` resolve
to the same row). Re-registering the same phone is an idempotent upsert: the
profile is replaced, `verified` is NOT reset if the user was already verified
— this requires `register()` to read the existing record first (if present)
and preserve its `verified` value, rather than always writing `False`.

`WHATSAPP_BOT_NUMBER` is a new setting (`whatsapp_bot_number` on
`FrameworkSettings`, or a `prana.config` constant — implementation detail for
the plan) used only to build the deep link shown to the user; it is the
business's own WhatsApp number, not the user's.

A `user_repo` singleton is needed at module scope in `backend/main.py`
(constructed via `SQLiteUserRepository(DATABASE_URL)`, mirroring the pattern
already used in `prana/bot/bootstrap.py`).

### 2.3 Webhook activation handshake — `prana/bot/whatsapp_webhook.py`

Current behavior: unknown phone -> static "reply START to set up" message;
known phone -> agent flow. This becomes a three-way branch:

```python
user = await user_repo.get_by_phone(phone)

if user is None:
    await messaging.send(channel="whatsapp", recipient=phone,
        body="Welcome to PRANA. Please register in the app first.")
    return Response(status_code=200)

if not user.metadata.get("verified", False):
    user.metadata["verified"] = True
    await user_repo.upsert(user)
    await messaging.send(channel="whatsapp", recipient=phone,
        body="You're all set! PRANA will alert you when conditions turn risky.")
    return Response(status_code=200)

# verified — existing agent flow, unchanged
ag = make_agent(provider, registry, max_steps=settings.agent_max_steps,
                temperature=settings.agent_temperature)
result = await ag.run(text, user)
await messaging.send(channel="whatsapp", recipient=phone,
                     body=result.answer or "Sorry, please try again.")
return Response(status_code=200)
```

Signature verification, payload parsing, and the verified-agent-flow branch
are unchanged from the existing implementation. The only new logic is the
`verified` check inserted between the existing "unknown user" and "run agent"
branches.

## 3. Flutter App Changes

### 3.1 New structure

```
mobile_app/lib/
  main.dart                       # MaterialApp shell + theme; home: OnboardingScreen
  models/
    user_registration.dart        # RegistrationRequest, HomeProfile
  services/
    api_client.dart                # PranaApiClient: register(), getCurrentRisk()
  screens/
    onboarding_screen.dart         # NEW
    dashboard_screen.dart          # MOVED from main.dart, behavior unchanged
```

### 3.2 `PranaApiClient` (`services/api_client.dart`)

Centralizes the backend base URL (currently a raw `TextEditingController` the
dashboard owns directly) and exposes:

```dart
class PranaApiClient {
  PranaApiClient({required this.baseUrl});
  final String baseUrl;

  Future<RegisterResult> register(RegistrationRequest req) async { ... }
  Future<Map<String, dynamic>> getCurrentRisk({
    required double lat, required double lon,
    required String locationName, required double? urbanHeatOffset,
  }) async { ... }
}
```

`getCurrentRisk` wraps the exact `POST /risk/current` call the dashboard
already makes today — same URL, same JSON shape, same error handling
(non-2xx throws `Exception`) — just moved out of `_PranaDashboardState` and
into the client so both screens share one HTTP implementation.

### 3.3 `OnboardingScreen` (`screens/onboarding_screen.dart`)

Form fields: phone (`TextField`), "Use GPS" button + location name field
(reusing the existing `geolocator` permission/fetch logic, moved here
verbatim from `_PranaDashboardState._useCurrentLocation`), AC (`Switch`),
roof material (`DropdownButtonFormField`: concrete/tin/other), floor level
(`DropdownButtonFormField`: ground/middle/top).

On "Register" tap: validate phone is non-empty and lat/lon are set (GPS was
used or manually entered — manual lat/lon fields are NOT exposed in this
screen; GPS is required to proceed, simplifying validation versus the
dashboard's manual-entry fallback), call `apiClient.register(...)`.

On success: show a confirmation card with an "Open WhatsApp" button
(`url_launcher.launchUrl` on the returned `whatsapp_link`) and a "Continue to
Dashboard" button that navigates to `DashboardScreen` regardless of whether
the user has tapped WhatsApp yet — registration and WhatsApp activation are
decoupled; the dashboard's `/risk/current` flow does not depend on
`verified`.

On failure (non-2xx or network error): show the error inline, same pattern
as the dashboard's existing `_statusMessage` handling.

### 3.4 New dependency

`url_launcher: ^6.3.0` added to `pubspec.yaml` (for the `wa.me` deep link).

## 4. Testing

### 4.1 Backend (pytest, mocks only, mirroring existing patterns)

- SQLite migration: construct a `SQLiteUserRepository` against a temp DB file
  that already has a `users` table WITHOUT the `verified` column (simulating
  a pre-existing database); confirm construction doesn't raise, and a
  subsequent `upsert`/`get` round-trips `verified` correctly.
- `POST /register` with a valid payload -> 200, `SQLiteUserRepository` (or a
  mocked one) received the upsert, response has `verified: false` and a
  `whatsapp_link` containing the phone-independent bot number.
- `POST /register` with invalid `lat`/`lon`/`phone` -> 422.
- `POST /register` twice for the same phone with `verified` already `True`
  the second time around does NOT reset it to `False` (preserves verified
  state across re-registration).
- Webhook: phone not in repo -> "register in the app first" message, 200,
  no agent/tool call attempted.
- Webhook: phone in repo with `verified=False`, any inbound text -> repo
  shows `verified=True` after, activation reply sent, no agent/tool call
  attempted for this message.
- Webhook: phone in repo with `verified=True` -> existing agent-flow test
  (already in `tests/prana/test_whatsapp_webhook.py`) continues to pass
  unmodified — explicit regression check.
- Forged-signature -> 403 test continues to pass unmodified — explicit
  regression check (signature verification code is untouched).

### 4.2 Flutter (widget test)

- Pump `OnboardingScreen` with a fake/mocked `PranaApiClient`, fill phone +
  simulate a GPS result + select home profile fields, tap "Register"; assert
  the mocked client's `register` was called with a `RegistrationRequest`
  matching the entered values exactly.
- After a successful mocked `register` response, assert the "Open WhatsApp"
  button is rendered and a "Continue to Dashboard" button is present.

## 5. Out of Scope (named explicitly)

- Editing or deleting an existing registration.
- Multiple users sharing one phone number, or one user with multiple phones.
- Rate-limiting `/register`.
- OTP-based verification (explicitly rejected in favor of WhatsApp opt-in).
- Email/name fields (considered and declined during brainstorming).
- Any change to the existing dashboard's risk-calculation behavior — it is
  relocated to its own file with identical logic, not redesigned.
- Manual lat/lon entry on the onboarding screen (GPS-only; the existing
  dashboard's manual lat/lon fields are untouched and remain available there
  for ad-hoc location testing, just not part of registration).

## 6. Risks Carried Forward From the Framework Build

- `SQLiteUserRepository.upsert` is a full-row replace (no partial merge) —
  the `register()` re-registration logic must explicitly read-before-write
  to preserve `verified`, per §2.2.
- The webhook's existing HMAC signature verification and message parsing are
  not touched by this feature; both have explicit regression tests (§4.1)
  precisely because a prior review caught a private-attribute-access issue
  in this same file and any future change to it deserves the same scrutiny.
