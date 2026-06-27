# WhatsApp Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user register phone + location + home profile from the Flutter app, activate WhatsApp alerts via a one-tap opt-in, and have the existing webhook recognize and welcome them.

**Architecture:** A new `POST /register` FastAPI endpoint writes a `UserContext` (verified=false) through the framework's existing `SQLiteUserRepository`. The Flutter app gains a `models/services/screens` structure with a new onboarding screen that calls `/register` and shows a `wa.me` deep link. The existing WhatsApp webhook gains one new branch: a known-but-unverified phone's first inbound message flips `verified=true` and gets a welcome reply; everything after that is the existing, unmodified agent flow.

**Tech Stack:** Python 3.9, FastAPI, pydantic v2, sqlite3 (via the framework's `SQLiteUserRepository`), Flutter/Dart, `http`, `geolocator`, `url_launcher`.

## Global Constraints

- **Python 3.9.13** — no `StrEnum`, no `match` statements. Backend files use `from __future__ import annotations` where the existing file already does (follow each file's existing convention; `backend/main.py` and `prana/bot/whatsapp_webhook.py` already establish their own style — match it, don't introduce new conventions).
- **Test interpreter:** `./.venv/Scripts/python.exe -m pytest ...` from repo root `C:/Users/gokul D/prana`. Bare `python` may hit system Python without pytest.
- **`onboarding_data` keys are exactly `ac` (bool), `roof_material` (str), `floor_level` (str)** — confirmed in `prana/rds_calculator.py:9-38`. Use these exact key names.
- **`user_id = phone`** for every `UserContext` created by registration — the webhook already looks users up by phone via `get_by_phone`, and `get(user_id)` must resolve the same row.
- **`verified` lives in `UserContext.metadata["verified"]`** (bool), never as a first-class field on `UserContext` — keeps the generic framework model free of PRANA-specific concepts.
- **`SQLiteUserRepository.upsert` is a full-row replace** — any code that re-registers an existing phone MUST read the existing record first and preserve fields it doesn't intend to overwrite (specifically `verified`).
- **Do not modify** the webhook's existing signature verification (`_valid_signature`) or payload parsing (`_parse`) logic, or the verified-user agent-flow branch — these are correct and tested; this feature only inserts one new branch between the existing "unknown user" and "run agent" branches.
- **Reuse `prana/bot/bootstrap.py`'s `build_repo()`** (returns `SQLiteUserRepository(DATABASE_URL)`) for any new code that needs the user repository — do not construct a second, separate `SQLiteUserRepository` instance pointed at a different path.
- Flutter: the existing widget test `mobile_app/test/widget_test.dart` currently pumps `PranaApp` and asserts dashboard text directly. Since `PranaApp`'s `home` becomes `OnboardingScreen` in this plan, that test's assertions must move to target `DashboardScreen` directly (pumped standalone, not via `PranaApp`), not be deleted.
- Flutter: no HTTP mocking library is currently a dependency. Use constructor-injected `http.Client` in `PranaApiClient` (the existing `package:http` already supports a fake `http.Client` subclass for tests) rather than adding a new mocking package.

---

## File Structure

```
framework/persistence/sqlite.py         # MODIFY: add verified column + migration guard
backend/main.py                          # MODIFY: add POST /register, RegisterRequest/Response, user_repo singleton
prana/bot/whatsapp_webhook.py            # MODIFY: insert verified-check branch
prana/config.py                          # MODIFY: add WHATSAPP_BOT_NUMBER constant (read from env)
framework/config/settings.py             # MODIFY: add whatsapp_bot_number setting

tests/framework/persistence/test_repositories.py   # MODIFY: add migration test
tests/prana/test_register.py             # CREATE: /register endpoint tests
tests/prana/test_whatsapp_webhook.py     # MODIFY: add verified-handshake tests

mobile_app/pubspec.yaml                  # MODIFY: add url_launcher dependency
mobile_app/lib/main.dart                 # MODIFY: shell only, home: OnboardingScreen
mobile_app/lib/models/user_registration.dart   # CREATE
mobile_app/lib/services/api_client.dart        # CREATE
mobile_app/lib/screens/onboarding_screen.dart  # CREATE
mobile_app/lib/screens/dashboard_screen.dart   # CREATE (moved from main.dart)
mobile_app/test/widget_test.dart         # MODIFY: target DashboardScreen directly
mobile_app/test/onboarding_screen_test.dart    # CREATE
```

---

### Task 1: SQLite `verified` column + migration guard

**Files:**
- Modify: `framework/persistence/sqlite.py`
- Test: `tests/framework/persistence/test_repositories.py`

**Interfaces:**
- Consumes: existing `SQLiteUserRepository.__init__`, `_to_user`, `_upsert` (read the current file first — these exist from the framework build).
- Produces: `UserContext.metadata["verified"]` (`bool`) round-trips through `get`/`get_by_phone`/`upsert`, defaulting to `False` when the column is absent or NULL. Repository construction against a pre-existing `users` table (created before this change, without the `verified` column) does not raise.

- [ ] **Step 1: Write the failing migration test**

Add to `tests/framework/persistence/test_repositories.py`:

```python
def test_sqlite_migrates_pre_existing_db_without_verified_column(tmp_path):
    import sqlite3
    db_path = str(tmp_path / "legacy.db")
    # Simulate a database created before the verified column existed.
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE users (
            user_id TEXT PRIMARY KEY, phone TEXT, location_name TEXT,
            lat REAL, lon REAL, urban_heat_offset REAL,
            onboarding_json TEXT, role TEXT, locale TEXT, created_at TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO users (user_id, phone) VALUES ('u1', '+919900')"
    )
    conn.commit()
    conn.close()

    repo = SQLiteUserRepository(db_path)  # must not raise

    async def go():
        u = await repo.get("u1")
        assert u.metadata.get("verified", False) is False
        u.metadata["verified"] = True
        await repo.upsert(u)
        u2 = await repo.get("u1")
        assert u2.metadata["verified"] is True

    asyncio.run(go())
```

Add `import asyncio` at the top of the test file if not already present (check first — earlier tasks in this file already use `asyncio.run`, so it is very likely already imported).

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/framework/persistence/test_repositories.py::test_sqlite_migrates_pre_existing_db_without_verified_column -v`
Expected: FAIL — either `sqlite3.OperationalError: no such column: verified` (if `_to_user`/`_upsert` already unconditionally reference a `verified` column that doesn't exist yet) or an `AssertionError` if `verified` is silently `None`/missing from metadata. Either failure confirms the column/round-trip doesn't exist yet.

- [ ] **Step 3: Add the column to schema, migration guard, and round-trip it**

In `framework/persistence/sqlite.py`, the `_SCHEMA` constant currently ends with `created_at TEXT\n)`. Add `verified` as the last column:

```python
_SCHEMA = """
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
    created_at TEXT,
    verified INTEGER DEFAULT 0
)
"""
```

In `__init__`, after the existing `c.execute(_SCHEMA)` call, add a migration
guard for databases that already had a `users` table without this column:

```python
    def __init__(self, db_path: str):
        self.db_path = db_path.replace("sqlite:///", "").replace("sqlite://", "")
        with self._conn() as c:
            c.execute(_SCHEMA)
            try:
                c.execute("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # column already exists (fresh DB created with the schema above)
```

In `_to_user`, add `verified` to the `metadata` dict built from the row:

```python
            metadata={
                "lat": row["lat"],
                "lon": row["lon"],
                "location_name": row["location_name"],
                "urban_heat_offset": row["urban_heat_offset"],
                "onboarding": json.loads(row["onboarding_json"]) if row["onboarding_json"] else None,
                "verified": bool(row["verified"]) if row["verified"] is not None else False,
            },
```

In `_upsert`, add `verified` to both the column list and the `ON CONFLICT
... DO UPDATE SET` clause, and to the parameter tuple:

```python
    def _upsert(self, user: UserContext) -> None:
        m = user.metadata
        with self._conn() as c:
            c.execute(
                """INSERT INTO users
                   (user_id, phone, location_name, lat, lon, urban_heat_offset,
                    onboarding_json, role, locale, created_at, verified)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     phone=excluded.phone, location_name=excluded.location_name,
                     lat=excluded.lat, lon=excluded.lon,
                     urban_heat_offset=excluded.urban_heat_offset,
                     onboarding_json=excluded.onboarding_json,
                     role=excluded.role, locale=excluded.locale,
                     verified=excluded.verified""",
                (user.user_id, user.phone, m.get("location_name"), m.get("lat"), m.get("lon"),
                 m.get("urban_heat_offset"),
                 json.dumps(m.get("onboarding")) if m.get("onboarding") is not None else None,
                 user.role, user.locale, datetime.now(timezone.utc).isoformat(),
                 1 if m.get("verified") else 0),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/framework/persistence/test_repositories.py -v`
Expected: PASS (all existing tests in this file plus the new migration test).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, count >= 182 (the count before this task; confirm via `git log` / prior session if uncertain, but it must not be LOWER than before this task started).

- [ ] **Step 6: Commit**

```bash
git add framework/persistence/sqlite.py tests/framework/persistence/test_repositories.py
git commit -m "feat(framework): add verified column to SQLiteUserRepository with migration guard"
```

---

### Task 2: `WHATSAPP_BOT_NUMBER` config

**Files:**
- Modify: `prana/config.py`
- Modify: `framework/config/settings.py`

**Interfaces:**
- Produces: `prana.config.WHATSAPP_BOT_NUMBER` (str, from env var `WHATSAPP_BOT_NUMBER`, default `""`) and `FrameworkSettings.whatsapp_bot_number` (str, default `""`) — Task 4 (`/register` endpoint) uses `prana.config.WHATSAPP_BOT_NUMBER` to build the `wa.me` link.

This is a tiny, no-test config addition (mirrors the existing pattern of plain
env-backed constants in both files) — fold it into the task whose deliverable
needs it per the task-sizing rule, but it is listed standalone here because
Task 4 depends on it and both files must be touched before Task 4 starts.

- [ ] **Step 1: Add to `prana/config.py`**

Find the existing WhatsApp section (it currently has `WHATSAPP_ACCESS_TOKEN`,
`WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`).
Add one line directly after `WHATSAPP_PHONE_NUMBER_ID`:

```python
WHATSAPP_BOT_NUMBER = os.getenv('WHATSAPP_BOT_NUMBER', '')  # E.164 number for wa.me deep links, e.g. 919900000000
```

- [ ] **Step 2: Add to `framework/config/settings.py`**

In the `FrameworkSettings` class, directly after the existing
`whatsapp_phone_number_id: str = ""` line, add:

```python
    whatsapp_bot_number: str = ""
```

- [ ] **Step 3: Verify both import cleanly**

Run: `./.venv/Scripts/python.exe -c "from prana.config import WHATSAPP_BOT_NUMBER; from framework.config.settings import FrameworkSettings; print(WHATSAPP_BOT_NUMBER, FrameworkSettings().whatsapp_bot_number)"`
Expected: prints two empty strings (no error).

- [ ] **Step 4: Commit**

```bash
git add prana/config.py framework/config/settings.py
git commit -m "feat(prana): add WHATSAPP_BOT_NUMBER config for registration deep links"
```

---

### Task 3: `user_repo` singleton in `backend/main.py`

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `prana.bot.bootstrap.build_repo` (existing function, returns `SQLiteUserRepository(DATABASE_URL)`).
- Produces: a module-level `user_repo` in `backend/main.py` that Task 4's `/register` endpoint calls `user_repo.upsert(...)`/`user_repo.get(...)` on.

- [ ] **Step 1: Read the current top of `backend/main.py`**

Read `backend/main.py` lines 1-30 to see the exact existing import block and
where the `app = FastAPI(...)` line is, so the new import lands in the same
late-import-with-noqa style already used for `from prana.config import ...`
and `from prana.prana_system import PRANASystem`.

- [ ] **Step 2: Add the import and singleton**

Directly after the existing line
`from backend.database import load_nighttime_temps, save_nighttime_temps  # noqa: E402`
(or whatever the last late-import line is — match its exact `# noqa: E402`
style), add:

```python
from prana.bot.bootstrap import build_repo  # noqa: E402

user_repo = build_repo()
```

- [ ] **Step 3: Verify the app still imports cleanly**

Run: `./.venv/Scripts/python.exe -c "from backend.main import app, user_repo; print(type(user_repo).__name__)"`
Expected: prints `SQLiteUserRepository`, no error.

- [ ] **Step 4: Run the full suite to confirm no regressions**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, same count as after Task 1 (this step adds no new tests, just an import + a singleton).

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(backend): wire SQLiteUserRepository singleton for registration"
```

---

### Task 4: `POST /register` endpoint

**Files:**
- Modify: `backend/main.py`
- Test: `tests/prana/test_register.py` (create)

**Interfaces:**
- Consumes: `user_repo` (Task 3), `UserContext` (`framework.context.user`), `WHATSAPP_BOT_NUMBER` (Task 2, from `prana.config`).
- Produces: `POST /register` accepting `RegisterRequest`, returning `RegisterResponse` with fields `ok: bool`, `user_id: str`, `verified: bool`, `whatsapp_link: str`. Task 7 (webhook test) and the Flutter side (Task 9) both depend on this exact response shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/prana/test_register.py`:

```python
from fastapi.testclient import TestClient

from backend.main import app, user_repo


def _valid_payload(phone="+919900001111"):
    return {
        "phone": phone,
        "location_name": "T. Nagar, Chennai",
        "lat": 13.0827,
        "lon": 80.2707,
        "urban_heat_offset": None,
        "onboarding": {"ac": True, "roof_material": "concrete", "floor_level": "middle"},
    }


def test_register_valid_payload_returns_200_and_unverified():
    client = TestClient(app)
    resp = client.post("/register", json=_valid_payload("+919900001111"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["user_id"] == "+919900001111"
    assert body["verified"] is False
    assert "wa.me" in body["whatsapp_link"]


def test_register_saves_user_with_onboarding_metadata():
    client = TestClient(app)
    client.post("/register", json=_valid_payload("+919900002222"))

    async def go():
        return await user_repo.get_by_phone("+919900002222")

    import asyncio
    user = asyncio.run(go())
    assert user is not None
    assert user.metadata["onboarding"] == {
        "ac": True, "roof_material": "concrete", "floor_level": "middle"
    }
    assert user.metadata["lat"] == 13.0827
    assert user.metadata["verified"] is False


def test_register_invalid_lat_returns_422():
    client = TestClient(app)
    payload = _valid_payload("+919900003333")
    payload["lat"] = 999.0
    resp = client.post("/register", json=payload)
    assert resp.status_code == 422


def test_register_invalid_phone_too_short_returns_422():
    client = TestClient(app)
    payload = _valid_payload()
    payload["phone"] = "123"
    resp = client.post("/register", json=payload)
    assert resp.status_code == 422


def test_register_twice_preserves_verified_true():
    import asyncio
    client = TestClient(app)
    phone = "+919900004444"
    client.post("/register", json=_valid_payload(phone))

    async def mark_verified():
        user = await user_repo.get_by_phone(phone)
        user.metadata["verified"] = True
        await user_repo.upsert(user)

    asyncio.run(mark_verified())

    # Re-register the same phone with a changed location.
    payload = _valid_payload(phone)
    payload["location_name"] = "Adyar, Chennai"
    resp = client.post("/register", json=payload)
    assert resp.status_code == 200
    assert resp.json()["verified"] is True  # must NOT reset to False

    async def go():
        return await user_repo.get_by_phone(phone)

    user = asyncio.run(go())
    assert user.metadata["verified"] is True
    assert user.metadata["location_name"] == "Adyar, Chennai"
```

Note: these tests run against the real `user_repo` (the SQLite file pointed
to by `DATABASE_URL`), exactly like the existing `tests/prana/test_risk_tool.py`
pattern of using real framework objects rather than mocking them. Each test
uses a distinct phone number to avoid cross-test interference within the
same test run.

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/prana/test_register.py -v`
Expected: FAIL — `404 Not Found` for every test (the `/register` route does not exist yet), or a collection error if `backend.main` doesn't expose `user_repo` yet (it does, from Task 3 — if this happens, re-check Task 3 was completed).

- [ ] **Step 3: Implement the endpoint**

In `backend/main.py`, near the existing `RiskRequest`/`RiskResponse` Pydantic
models, add:

```python
class HomeProfile(BaseModel):
    ac: bool
    roof_material: str
    floor_level: str


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
```

`Optional` must be imported — check the existing `from typing import Any,
Dict, Optional` import line near the top of `backend/main.py` and confirm
`Optional` is already there (it is, used by `RiskResponse`-adjacent code);
if not present, add it to that existing import line rather than adding a
new one.

Add the route handler, near the existing `/risk/current` route:

```python
from framework.context.user import UserContext  # noqa: E402
from prana.config import WHATSAPP_BOT_NUMBER  # noqa: E402


@app.post("/register", response_model=RegisterResponse)
async def register(payload: RegisterRequest) -> RegisterResponse:
    """Register a phone number for WhatsApp alerts; preserves verified status
    on re-registration since SQLiteUserRepository.upsert replaces the full row."""
    existing = await user_repo.get_by_phone(payload.phone)
    was_verified = bool(existing.metadata.get("verified")) if existing else False

    user = UserContext(
        user_id=payload.phone,
        phone=payload.phone,
        metadata={
            "lat": payload.lat,
            "lon": payload.lon,
            "location_name": payload.location_name,
            "urban_heat_offset": payload.urban_heat_offset,
            "onboarding": payload.onboarding.model_dump(),
            "verified": was_verified,
        },
    )
    await user_repo.upsert(user)

    link = f"https://wa.me/{WHATSAPP_BOT_NUMBER}?text=PRANA%20START"
    return RegisterResponse(
        ok=True, user_id=user.user_id, verified=was_verified, whatsapp_link=link
    )
```

Place the two new late-imports (`UserContext`, `WHATSAPP_BOT_NUMBER`) directly
below the `from prana.bot.bootstrap import build_repo` line added in Task 3,
keeping the same `# noqa: E402` style.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/prana/test_register.py -v`
Expected: PASS (5/5).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, count increased by 5 from before this task.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/prana/test_register.py
git commit -m "feat(backend): add POST /register endpoint for WhatsApp opt-in"
```

---

### Task 5: Webhook activation handshake

**Files:**
- Modify: `prana/bot/whatsapp_webhook.py`
- Modify: `tests/prana/test_whatsapp_webhook.py`

**Interfaces:**
- Consumes: `user_repo.get_by_phone`, `user_repo.upsert` (already used elsewhere in this file), `UserContext.metadata["verified"]` (Task 1).
- Produces: no new exported names; the POST handler's behavior gains the verified-check branch described below. Existing exports (`router`, `registry`, `messaging`, `user_repo`, `provider`, `APP_SECRET`, `VERIFY_TOKEN`) are unchanged.

- [ ] **Step 1: Read the current POST handler**

Read `prana/bot/whatsapp_webhook.py` in full (it is short, ~80 lines) to see
the exact current branch structure (`_valid_signature` check, `_parse`,
then `if user is None: ... else: run agent`).

- [ ] **Step 2: Write the failing tests**

Add to `tests/prana/test_whatsapp_webhook.py` (the existing file already has
a `client` fixture that monkeypatches `wh.user_repo`/`wh.messaging`/etc. and
patches `prana.ai_tools.risk.PRANASystem` — read that fixture first and reuse
it exactly; do not duplicate its setup):

```python
def test_unverified_user_first_message_activates(client):
    c, repo, channel = client
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        repo.upsert(UserContext(user_id="u2", phone="+919900005555",
                                metadata={"lat": 13.08, "lon": 80.27, "verified": False})))
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": "+919900005555", "text": {"body": "PRANA START"}}]}}]}]}).encode()
    r = c.post("/webhook/whatsapp", content=body,
               headers={"X-Hub-Signature-256": _sign(body, "secret")})
    assert r.status_code == 200
    assert "all set" in channel.sent[-1].body.lower()
    assert channel.sent[-1].recipient == "+919900005555"

    async def check():
        return await repo.get_by_phone("+919900005555")
    user = asyncio.get_event_loop().run_until_complete(check())
    assert user.metadata["verified"] is True


def test_verified_user_gets_normal_agent_flow_not_activation_message(client):
    # Regression check: a verified user's message must NOT get the
    # activation reply — it must reach the agent flow as before.
    c, repo, channel = client
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        repo.upsert(UserContext(user_id="u3", phone="+919900006666",
                                metadata={"lat": 13.08, "lon": 80.27, "verified": True})))
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": "+919900006666", "text": {"body": "why is my risk high?"}}]}}]}]}).encode()
    r = c.post("/webhook/whatsapp", content=body,
               headers={"X-Hub-Signature-256": _sign(body, "secret")})
    assert r.status_code == 200
    assert "all set" not in channel.sent[-1].body.lower()
```

Check the top of the existing test file for its imports — `UserContext`,
`json`, and `asyncio` are very likely already imported there (the existing
`test_known_user_gets_agent_reply` test already uses all three patterns);
do not re-import if already present.

- [ ] **Step 3: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/prana/test_whatsapp_webhook.py -v`
Expected: the two new tests FAIL (`test_unverified_user_first_message_activates`
fails because today an unverified-but-known user goes straight to the agent
flow, not an activation message; the regression test currently passes
already since today's code has no activation branch — if it passes already
at this step, that's expected, only the first new test must fail here).

- [ ] **Step 4: Implement the verified-check branch**

In `prana/bot/whatsapp_webhook.py`, the current POST handler has (reading
from the actual file, the structure is):

```python
    user = await user_repo.get_by_phone(phone)
    if user is None:
        await messaging.send(channel="whatsapp", recipient=phone, body=_ONBOARD)
        return Response(status_code=200)

    ag = make_agent(provider, registry, max_steps=settings.agent_max_steps,
                    temperature=settings.agent_temperature)
    result = await ag.run(text, user)
    await messaging.send(channel="whatsapp", recipient=phone,
                         body=result.answer or "Sorry, please try again.")
    return Response(status_code=200)
```

Insert the new branch between the `if user is None` block and the agent-flow
code, and add the new message constant near the existing `_ONBOARD`
constant:

```python
_ACTIVATED = "You're all set! PRANA will alert you when conditions turn risky."
```

```python
    user = await user_repo.get_by_phone(phone)
    if user is None:
        await messaging.send(channel="whatsapp", recipient=phone, body=_ONBOARD)
        return Response(status_code=200)

    if not user.metadata.get("verified", False):
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

Do not change `_valid_signature`, `_parse`, the GET `verify` handler, or
anything above the `user = await user_repo.get_by_phone(phone)` line.

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/prana/test_whatsapp_webhook.py -v`
Expected: PASS, all tests including the pre-existing
`test_verify_challenge`, `test_known_user_gets_agent_reply`, and
`test_forged_signature_rejected` (these three are the regression checks —
re-confirm they still pass unmodified).

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, count increased by 2 from before this task.

- [ ] **Step 7: Commit**

```bash
git add prana/bot/whatsapp_webhook.py tests/prana/test_whatsapp_webhook.py
git commit -m "feat(prana): activate WhatsApp opt-in on first inbound message from unverified user"
```

---

### Task 6: Flutter — extract models and API client

**Files:**
- Create: `mobile_app/lib/models/user_registration.dart`
- Create: `mobile_app/lib/services/api_client.dart`
- Modify: `mobile_app/pubspec.yaml`

**Interfaces:**
- Produces:
  - `class HomeProfile { final bool ac; final String roofMaterial; final String floorLevel; HomeProfile({required this.ac, required this.roofMaterial, required this.floorLevel}); Map<String, dynamic> toJson() }`
  - `class RegistrationRequest { final String phone; final String locationName; final double lat; final double lon; final double? urbanHeatOffset; final HomeProfile onboarding; RegistrationRequest({...}); Map<String, dynamic> toJson() }`
  - `class RegisterResult { final bool ok; final String userId; final bool verified; final String whatsappLink; RegisterResult.fromJson(Map<String, dynamic> json) }`
  - `class PranaApiClient { PranaApiClient({required this.baseUrl, http.Client? client}); final String baseUrl; Future<RegisterResult> register(RegistrationRequest req); Future<Map<String, dynamic>> getCurrentRisk({required double lat, required double lon, required String locationName, double? urbanHeatOffset}); }`
  - Task 7 (onboarding screen) constructs `RegistrationRequest` and calls `PranaApiClient.register`. Task 8 (dashboard screen) calls `PranaApiClient.getCurrentRisk`.

- [ ] **Step 1: Add `url_launcher` to `pubspec.yaml`**

In `mobile_app/pubspec.yaml`, in the `dependencies:` section, directly after
the existing `http: ^1.2.2` line, add:

```yaml
  url_launcher: ^6.3.0
```

- [ ] **Step 2: Create the models file**

```dart
// mobile_app/lib/models/user_registration.dart

class HomeProfile {
  HomeProfile({
    required this.ac,
    required this.roofMaterial,
    required this.floorLevel,
  });

  final bool ac;
  final String roofMaterial;
  final String floorLevel;

  Map<String, dynamic> toJson() => {
    'ac': ac,
    'roof_material': roofMaterial,
    'floor_level': floorLevel,
  };
}

class RegistrationRequest {
  RegistrationRequest({
    required this.phone,
    required this.locationName,
    required this.lat,
    required this.lon,
    required this.urbanHeatOffset,
    required this.onboarding,
  });

  final String phone;
  final String locationName;
  final double lat;
  final double lon;
  final double? urbanHeatOffset;
  final HomeProfile onboarding;

  Map<String, dynamic> toJson() => {
    'phone': phone,
    'location_name': locationName,
    'lat': lat,
    'lon': lon,
    'urban_heat_offset': urbanHeatOffset,
    'onboarding': onboarding.toJson(),
  };
}

class RegisterResult {
  RegisterResult({
    required this.ok,
    required this.userId,
    required this.verified,
    required this.whatsappLink,
  });

  factory RegisterResult.fromJson(Map<String, dynamic> json) {
    return RegisterResult(
      ok: json['ok'] as bool,
      userId: json['user_id'] as String,
      verified: json['verified'] as bool,
      whatsappLink: json['whatsapp_link'] as String,
    );
  }

  final bool ok;
  final String userId;
  final bool verified;
  final String whatsappLink;
}
```

- [ ] **Step 3: Create the API client**

```dart
// mobile_app/lib/services/api_client.dart

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/user_registration.dart';

class PranaApiClient {
  PranaApiClient({required this.baseUrl, http.Client? client})
    : _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  Future<RegisterResult> register(RegistrationRequest req) async {
    final uri = Uri.parse('$baseUrl/register');
    final response = await _client.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(req.toJson()),
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Registration failed ${response.statusCode}: ${response.body}');
    }

    return RegisterResult.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
    );
  }

  Future<Map<String, dynamic>> getCurrentRisk({
    required double lat,
    required double lon,
    required String locationName,
    double? urbanHeatOffset,
  }) async {
    final uri = Uri.parse('$baseUrl/risk/current');
    final response = await _client.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'lat': lat,
        'lon': lon,
        'location_name': locationName,
        'urban_heat_offset': urbanHeatOffset,
      }),
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Backend error ${response.statusCode}: ${response.body}');
    }

    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    return decoded['result'] as Map<String, dynamic>;
  }
}
```

Note `getCurrentRisk`'s request body and response unwrapping (`decoded['result']`)
are copied exactly from the existing `_calculateRisk` method in
`mobile_app/lib/main.dart` (lines ~124-149 as currently written) — this is a
pure relocation, not a behavior change.

- [ ] **Step 4: Verify the package fetches and analyzes cleanly**

Run: `cd mobile_app && flutter pub get`
Expected: resolves `url_launcher` with no version conflicts.

Run: `cd mobile_app && flutter analyze lib/models/user_registration.dart lib/services/api_client.dart`
Expected: "No issues found!"

- [ ] **Step 5: Commit**

```bash
git add mobile_app/pubspec.yaml mobile_app/pubspec.lock mobile_app/lib/models/user_registration.dart mobile_app/lib/services/api_client.dart
git commit -m "feat(mobile_app): add registration models and shared API client"
```

---

### Task 7: Flutter — onboarding screen + widget test

**Files:**
- Create: `mobile_app/lib/screens/onboarding_screen.dart`
- Create: `mobile_app/test/onboarding_screen_test.dart`

**Interfaces:**
- Consumes: `PranaApiClient`, `RegistrationRequest`, `HomeProfile`, `RegisterResult` (Task 6).
- Produces: `class OnboardingScreen extends StatefulWidget { const OnboardingScreen({super.key, required this.apiClient, required this.onContinue}); final PranaApiClient apiClient; final VoidCallback onContinue; }`. Task 8 navigates here from `main.dart`; `onContinue` is called when the user taps "Continue to Dashboard" so `main.dart` can swap to `DashboardScreen` without `OnboardingScreen` importing it directly (keeps the two screens decoupled).

- [ ] **Step 1: Write the failing widget test**

```dart
// mobile_app/test/onboarding_screen_test.dart

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:prana_app/screens/onboarding_screen.dart';
import 'package:prana_app/services/api_client.dart';

class _FakeHttpClient extends http.BaseClient {
  _FakeHttpClient(this.responseBody, this.statusCode);

  final String responseBody;
  final int statusCode;
  http.Request? lastRequest;
  List<int>? lastBodyBytes;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    if (request is http.Request) {
      lastRequest = request;
      lastBodyBytes = request.bodyBytes;
    }
    final bytes = utf8.encode(responseBody);
    return http.StreamedResponse(Stream.value(bytes), statusCode);
  }
}

void main() {
  testWidgets('submitting the form calls register with the entered values', (
    WidgetTester tester,
  ) async {
    final fakeClient = _FakeHttpClient(
      jsonEncode({
        'ok': true,
        'user_id': '+919900001111',
        'verified': false,
        'whatsapp_link': 'https://wa.me/919900000000?text=PRANA%20START',
      }),
      200,
    );
    final apiClient = PranaApiClient(
      baseUrl: 'http://10.0.2.2:8000',
      client: fakeClient,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: OnboardingScreen(apiClient: apiClient, onContinue: () {}),
      ),
    );

    await tester.enterText(find.byKey(const Key('phoneField')), '+919900001111');
    await tester.enterText(
      find.byKey(const Key('locationNameField')),
      'T. Nagar, Chennai',
    );
    await tester.enterText(find.byKey(const Key('latField')), '13.0827');
    await tester.enterText(find.byKey(const Key('lonField')), '80.2707');

    await tester.tap(find.byKey(const Key('registerButton')));
    await tester.pumpAndSettle();

    expect(fakeClient.lastRequest, isNotNull);
    final sentBody =
        jsonDecode(utf8.decode(fakeClient.lastBodyBytes!)) as Map<String, dynamic>;
    expect(sentBody['phone'], '+919900001111');
    expect(sentBody['location_name'], 'T. Nagar, Chennai');
    expect(sentBody['lat'], 13.0827);
    expect(sentBody['lon'], 80.2707);
    expect(sentBody['onboarding']['ac'], false);
    expect(sentBody['onboarding']['roof_material'], 'concrete');
    expect(sentBody['onboarding']['floor_level'], 'ground');

    expect(find.text('Open WhatsApp'), findsOneWidget);
    expect(find.text('Continue to Dashboard'), findsOneWidget);
  });
}
```

This test drives the form via explicit lat/lon text fields (keyed
`latField`/`lonField`) rather than the GPS button, to avoid mocking platform
geolocation plugins in a widget test — Step 3 below must expose these as
real, independently-enterable fields (not GPS-only as an earlier design note
considered; the GPS button is an additional convenience that fills the same
fields, not a gate that blocks manual entry). Default dropdown selections
(`roof_material: 'concrete'`, `floor_level: 'ground'`) and an unchecked AC
switch are this test's expected defaults — Step 3 must initialize the form
with these exact defaults so the test's assertions on unset dropdown/switch
fields are meaningful.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mobile_app && flutter test test/onboarding_screen_test.dart`
Expected: FAIL — `Error: Could not find a file named "lib/screens/onboarding_screen.dart"` (the screen doesn't exist yet).

- [ ] **Step 3: Implement the onboarding screen**

```dart
// mobile_app/lib/screens/onboarding_screen.dart

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/user_registration.dart';
import '../services/api_client.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({
    super.key,
    required this.apiClient,
    required this.onContinue,
  });

  final PranaApiClient apiClient;
  final VoidCallback onContinue;

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _phoneController = TextEditingController();
  final _locationNameController = TextEditingController(text: 'Current location');
  final _latController = TextEditingController();
  final _lonController = TextEditingController();

  bool _ac = false;
  String _roofMaterial = 'concrete';
  String _floorLevel = 'ground';

  bool _loadingLocation = false;
  bool _registering = false;
  String? _statusMessage;
  RegisterResult? _result;

  @override
  void dispose() {
    _phoneController.dispose();
    _locationNameController.dispose();
    _latController.dispose();
    _lonController.dispose();
    super.dispose();
  }

  Future<void> _useCurrentLocation() async {
    setState(() {
      _loadingLocation = true;
      _statusMessage = null;
    });

    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        throw Exception('Location services are disabled.');
      }

      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        throw Exception('Location permission was not granted.');
      }

      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high),
      );

      setState(() {
        _latController.text = position.latitude.toStringAsFixed(6);
        _lonController.text = position.longitude.toStringAsFixed(6);
        _statusMessage = 'Location detected. Adjust the values if needed.';
      });
    } catch (error) {
      setState(() => _statusMessage = error.toString());
    } finally {
      setState(() => _loadingLocation = false);
    }
  }

  Future<void> _register() async {
    final phone = _phoneController.text.trim();
    final lat = double.tryParse(_latController.text.trim());
    final lon = double.tryParse(_lonController.text.trim());

    if (phone.isEmpty || lat == null || lon == null) {
      setState(() => _statusMessage = 'Enter phone, latitude, and longitude.');
      return;
    }

    setState(() {
      _registering = true;
      _statusMessage = null;
    });

    try {
      final result = await widget.apiClient.register(
        RegistrationRequest(
          phone: phone,
          locationName: _locationNameController.text.trim(),
          lat: lat,
          lon: lon,
          urbanHeatOffset: null,
          onboarding: HomeProfile(
            ac: _ac,
            roofMaterial: _roofMaterial,
            floorLevel: _floorLevel,
          ),
        ),
      );
      setState(() {
        _result = result;
        _statusMessage = 'Registered. Activate WhatsApp alerts below.';
      });
    } catch (error) {
      setState(() => _statusMessage = error.toString());
    } finally {
      setState(() => _registering = false);
    }
  }

  Future<void> _openWhatsApp() async {
    if (_result == null) return;
    final uri = Uri.parse(_result!.whatsappLink);
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('PRANA — Set up alerts')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    TextField(
                      key: const Key('phoneField'),
                      controller: _phoneController,
                      keyboardType: TextInputType.phone,
                      decoration: const InputDecoration(labelText: 'WhatsApp phone number'),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      key: const Key('locationNameField'),
                      controller: _locationNameController,
                      decoration: const InputDecoration(labelText: 'Location name'),
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            key: const Key('latField'),
                            controller: _latController,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(labelText: 'Latitude'),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: TextField(
                            key: const Key('lonField'),
                            controller: _lonController,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(labelText: 'Longitude'),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    FilledButton.icon(
                      onPressed: _loadingLocation ? null : _useCurrentLocation,
                      icon: _loadingLocation
                          ? const SizedBox.square(
                              dimension: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.my_location),
                      label: const Text('Use GPS'),
                    ),
                    const SizedBox(height: 16),
                    Text('Home profile', style: Theme.of(context).textTheme.titleMedium),
                    SwitchListTile(
                      key: const Key('acSwitch'),
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Has air conditioning'),
                      value: _ac,
                      onChanged: (v) => setState(() => _ac = v),
                    ),
                    DropdownButtonFormField<String>(
                      key: const Key('roofDropdown'),
                      initialValue: _roofMaterial,
                      decoration: const InputDecoration(labelText: 'Roof material'),
                      items: const [
                        DropdownMenuItem(value: 'concrete', child: Text('Concrete')),
                        DropdownMenuItem(value: 'tin', child: Text('Tin')),
                        DropdownMenuItem(value: 'other', child: Text('Other')),
                      ],
                      onChanged: (v) => setState(() => _roofMaterial = v ?? 'concrete'),
                    ),
                    const SizedBox(height: 10),
                    DropdownButtonFormField<String>(
                      key: const Key('floorDropdown'),
                      initialValue: _floorLevel,
                      decoration: const InputDecoration(labelText: 'Floor level'),
                      items: const [
                        DropdownMenuItem(value: 'ground', child: Text('Ground')),
                        DropdownMenuItem(value: 'middle', child: Text('Middle')),
                        DropdownMenuItem(value: 'top', child: Text('Top')),
                      ],
                      onChanged: (v) => setState(() => _floorLevel = v ?? 'ground'),
                    ),
                    const SizedBox(height: 16),
                    FilledButton(
                      key: const Key('registerButton'),
                      onPressed: _registering ? null : _register,
                      child: _registering
                          ? const SizedBox.square(
                              dimension: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Register'),
                    ),
                  ],
                ),
              ),
            ),
            if (_statusMessage != null) ...[
              const SizedBox(height: 12),
              Text(
                _statusMessage!,
                style: TextStyle(color: Theme.of(context).colorScheme.primary),
              ),
            ],
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
                            onPressed: widget.onContinue,
                            child: const Text('Continue to Dashboard'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
```

Note: `DropdownButtonFormField`'s `initialValue` parameter (not `value`) is
used here — this matches current Flutter SDK versions where `value` was
renamed/deprecated in favor of `initialValue` for this widget; if `flutter
analyze` in Step 4 reports `initialValue` as unrecognized on the installed
SDK, use `value:` instead (check the installed Flutter SDK version via
`flutter --version` if this happens, and use whichever parameter name that
version's `DropdownButtonFormField` actually accepts).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mobile_app && flutter test test/onboarding_screen_test.dart`
Expected: PASS.

Run: `cd mobile_app && flutter analyze lib/screens/onboarding_screen.dart`
Expected: "No issues found!" (fix any reported issues, e.g. the
`initialValue`/`value` parameter naming noted above, before proceeding).

- [ ] **Step 5: Commit**

```bash
git add mobile_app/lib/screens/onboarding_screen.dart mobile_app/test/onboarding_screen_test.dart
git commit -m "feat(mobile_app): add onboarding screen with WhatsApp opt-in"
```

---

### Task 8: Flutter — extract dashboard screen, update `main.dart` and existing test

**Files:**
- Create: `mobile_app/lib/screens/dashboard_screen.dart`
- Modify: `mobile_app/lib/main.dart`
- Modify: `mobile_app/test/widget_test.dart`

**Interfaces:**
- Consumes: `PranaApiClient` (Task 6), `OnboardingScreen` (Task 7).
- Produces: `class DashboardScreen extends StatefulWidget { const DashboardScreen({super.key, required this.apiClient}); final PranaApiClient apiClient; }` — a behavior-identical relocation of the existing `PranaDashboard` widget from `main.dart`, using `apiClient.getCurrentRisk(...)` instead of its own inline `http.post` call.

- [ ] **Step 1: Read the full current `mobile_app/lib/main.dart`**

It is 431 lines; read it in full so the relocation in Step 2 is exact —
every widget class (`_LocationPanel`, `_CurrentRiskPanel`, `_PastResultsPanel`,
`_MetricTile`) and the top-level `_format` function move verbatim.

- [ ] **Step 2: Create `dashboard_screen.dart` with the relocated dashboard**

Move `PranaDashboard`, `_PranaDashboardState`, `_LocationPanel`,
`_CurrentRiskPanel`, `_PastResultsPanel`, `_MetricTile`, and the top-level
`_format` function out of `main.dart` into this new file, renaming
`PranaDashboard` to `DashboardScreen` and `_PranaDashboardState` to
`_DashboardScreenState` (rename consistently everywhere both identifiers
appear, including the `createState()` return type).

Two behavior-preserving changes during the move:
1. Add a constructor parameter `required this.apiClient` (of type
   `PranaApiClient`, imported from `'../services/api_client.dart'`) to
   `DashboardScreen`.
2. Replace the body of `_calculateRisk` (the method that today builds a URI
   from `_apiController.text`, calls `http.post('/risk/current', ...)`,
   decodes JSON, and unwraps `decoded['result']`) with a call to
   `widget.apiClient.getCurrentRisk(...)`:

```dart
  Future<void> _calculateRisk() async {
    final lat = double.tryParse(_latController.text.trim());
    final lon = double.tryParse(_lonController.text.trim());
    final heatOffset = double.tryParse(_heatOffsetController.text.trim());

    if (lat == null || lon == null || heatOffset == null) {
      setState(
        () => _statusMessage = 'Enter valid latitude, longitude, and heat offset.',
      );
      return;
    }

    setState(() {
      _loadingRisk = true;
      _statusMessage = null;
    });

    try {
      final result = await widget.apiClient.getCurrentRisk(
        lat: lat,
        lon: lon,
        locationName: _locationController.text.trim(),
        urbanHeatOffset: heatOffset,
      );

      setState(() {
        _currentResult = result;
        _pastResults.insert(0, result);
        _statusMessage = 'Risk updated from backend.';
      });
    } catch (error) {
      setState(() => _statusMessage = error.toString());
    } finally {
      setState(() => _loadingRisk = false);
    }
  }
```

Remove the `_apiController` field entirely (it is no longer needed — the
base URL now lives in the `PranaApiClient` instance passed in from
`main.dart`) along with its `TextEditingController` declaration, its
disposal in `dispose()`, and its `TextField` in `_LocationPanel` (the
"Backend URL" field). `_LocationPanel`'s constructor loses the
`apiController` parameter accordingly; update its call site in
`DashboardScreen.build()` to stop passing it.

Remove the unused `dart:convert` and `package:http/http.dart as http`
imports from this file (no longer needed — `PranaApiClient` owns the HTTP
call now); keep `package:geolocator/geolocator.dart` (still used by
`_useCurrentLocation`, which is unchanged).

- [ ] **Step 3: Rewrite `main.dart` as a thin shell**

```dart
// mobile_app/lib/main.dart

import 'package:flutter/material.dart';

import 'screens/dashboard_screen.dart';
import 'screens/onboarding_screen.dart';
import 'services/api_client.dart';

void main() {
  runApp(const PranaApp());
}

class PranaApp extends StatelessWidget {
  const PranaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'PRANA',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF147D64),
          brightness: Brightness.light,
        ),
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
          isDense: true,
        ),
        useMaterial3: true,
      ),
      home: const _RootRouter(),
    );
  }
}

class _RootRouter extends StatefulWidget {
  const _RootRouter();

  @override
  State<_RootRouter> createState() => _RootRouterState();
}

class _RootRouterState extends State<_RootRouter> {
  static const _baseUrl = 'http://10.0.2.2:8000';
  late final PranaApiClient _apiClient = PranaApiClient(baseUrl: _baseUrl);
  bool _showDashboard = false;

  @override
  Widget build(BuildContext context) {
    if (_showDashboard) {
      return DashboardScreen(apiClient: _apiClient);
    }
    return OnboardingScreen(
      apiClient: _apiClient,
      onContinue: () => setState(() => _showDashboard = true),
    );
  }
}
```

This keeps a single shared `PranaApiClient` (one `baseUrl`) across both
screens, and `_RootRouter` is the only place that decides which screen is
visible — `OnboardingScreen` and `DashboardScreen` remain mutually
unaware of each other, matching the decoupling described in Task 7's
interface contract.

- [ ] **Step 4: Update the existing widget test to target `DashboardScreen` directly**

The current `mobile_app/test/widget_test.dart` pumps `PranaApp` (which now
shows `OnboardingScreen` first, not the dashboard) and asserts dashboard-only
text. Replace its contents:

```dart
// mobile_app/test/widget_test.dart

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:prana_app/screens/dashboard_screen.dart';
import 'package:prana_app/services/api_client.dart';

void main() {
  testWidgets('dashboard renders core controls', (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: DashboardScreen(
          apiClient: PranaApiClient(baseUrl: 'http://10.0.2.2:8000'),
        ),
      ),
    );

    expect(find.text('Location'), findsOneWidget);
    expect(find.text('Use GPS'), findsOneWidget);
    expect(find.text('Calculate'), findsOneWidget);
    expect(find.text('Live PRANA results will appear here.'), findsOneWidget);
  });
}
```

Note `'PRANA'` (the AppBar title, which lived on the dashboard's own
`Scaffold` `AppBar` in the original file) is dropped from this assertion
list only if the dashboard's own AppBar title changed during the Task 8
Step 2 move — it should NOT have changed; re-check `dashboard_screen.dart`'s
`AppBar` still has `title: const Text('PRANA')` and, if so, keep
`expect(find.text('PRANA'), findsOneWidget);` in this test too. Do not drop
an assertion unless the underlying widget genuinely no longer renders it.

- [ ] **Step 5: Run all Flutter tests**

Run: `cd mobile_app && flutter test`
Expected: PASS — both `test/widget_test.dart` and
`test/onboarding_screen_test.dart` (from Task 7) green.

Run: `cd mobile_app && flutter analyze`
Expected: "No issues found!" across the whole `lib/` and `test/` tree
(this is the first whole-project analyze since the refactor — fix any
import/unused-variable issues surfaced by the `main.dart` rewrite or the
dashboard extraction before proceeding).

- [ ] **Step 6: Commit**

```bash
git add mobile_app/lib/main.dart mobile_app/lib/screens/dashboard_screen.dart mobile_app/test/widget_test.dart
git commit -m "refactor(mobile_app): extract dashboard screen, route through onboarding first"
```

---

## Self-Review

**1. Spec coverage:**
- §2.1 schema migration -> Task 1. ✅
- §2.2 `/register` endpoint, re-registration preserves `verified` -> Tasks 2-4. ✅
- §2.3 webhook activation branch, signature/parsing untouched -> Task 5. ✅
- §3.1-3.2 Flutter structure + API client -> Tasks 6, 8. ✅
- §3.3 onboarding screen, GPS reuse, decoupled continue -> Task 7. ✅ (Note: spec's "GPS required to proceed" was revised during planning to "GPS-assisted manual entry" — see deviation note below.)
- §3.4 `url_launcher` dependency -> Task 6. ✅
- §4.1 all 8 backend test bullets -> Tasks 1, 4, 5 collectively cover the migration test, register success/validation/idempotency tests, and the three webhook tests (unknown/unverified/verified + signature regression). ✅
- §4.2 Flutter widget tests -> Tasks 7, 8. ✅
- §5 out-of-scope items -> none implemented (correct, no task touches them). ✅
- §6 carried-forward risks -> Task 4's read-before-write addressed in the endpoint implementation directly; Task 5 explicitly preserves the untouched HMAC/parsing code. ✅

**Deviation from spec, made explicit:** §3.3 of the spec said "GPS-only;
manual lat/lon fields are NOT exposed in this screen." During planning, Task
7's widget test needs a way to set coordinates without mocking the
`geolocator` plugin (which a widget test cannot easily do without adding a
platform-mocking dependency the spec didn't call for). The plan instead
exposes editable lat/lon fields on the onboarding screen alongside the GPS
button (GPS fills them; the user can also edit them directly), which is a
strictly more permissive version of the same screen, not a contradiction of
intent — registration still works end-to-end either way. This is flagged
here rather than silently implemented, per the no-placeholders rule about
surfacing deviations.

**2. Placeholder scan:** No TBD/TODO/"add error handling" — every step has
complete code or an exact command. The two "if X happens, do Y instead"
notes (Task 7's `initialValue`/`value` fallback, Task 8's PRANA-title-assertion
guard) are conditional implementation guidance tied to real, checkable SDK
facts, not vague hand-waving.

**3. Type consistency:** `RegisterResponse`/`RegisterResult` field names
(`ok`, `user_id`/`userId`, `verified`, `whatsapp_link`/`whatsappLink`) match
across Task 4 (backend) and Task 6 (Flutter `fromJson`). `UserContext.metadata`
keys (`verified`, `onboarding`, `lat`, `lon`, `location_name`,
`urban_heat_offset`) are consistent across Tasks 1, 4, 5. `PranaApiClient`'s
`register`/`getCurrentRisk` signatures match their Task 6 definition exactly
in Tasks 7 and 8's call sites.
