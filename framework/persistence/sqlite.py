from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

from framework.context.user import UserContext

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

_CHECKINS_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    checkin_date TEXT NOT NULL,
    sleep_quality TEXT,
    outdoor_temp REAL,
    humidity REAL,
    created_at TEXT,
    UNIQUE(user_id, checkin_date)
)
"""


class SQLiteUserRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path.replace("sqlite:///", "").replace("sqlite://", "")
        with self._conn() as c:
            c.execute(_SCHEMA)
            try:
                c.execute("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # column already exists (fresh DB created with the schema above)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _to_user(row: sqlite3.Row) -> UserContext:
        return UserContext(
            user_id=row["user_id"],
            phone=row["phone"],
            role=row["role"] or "user",
            locale=row["locale"] or "en",
            metadata={
                "lat": row["lat"],
                "lon": row["lon"],
                "location_name": row["location_name"],
                "urban_heat_offset": row["urban_heat_offset"],
                "onboarding": json.loads(row["onboarding_json"]) if row["onboarding_json"] else None,
                "verified": bool(row["verified"]) if row["verified"] is not None else False,
            },
        )

    async def get_by_phone(self, phone: str) -> UserContext | None:
        return await asyncio.to_thread(self._query, "phone", phone)

    async def get(self, user_id: str) -> UserContext | None:
        return await asyncio.to_thread(self._query, "user_id", user_id)

    def _query(self, column: str, value: str) -> UserContext | None:
        with self._conn() as c:
            row = c.execute(f"SELECT * FROM users WHERE {column}=?", (value,)).fetchone()
        return self._to_user(row) if row else None

    async def upsert(self, user: UserContext) -> None:
        await asyncio.to_thread(self._upsert, user)

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


class SQLiteCheckinRepository:
    """Stores per-user nightly sleep check-ins, the evidence the personalization
    layer consumes. Shares the same SQLite file as the user repository."""

    def __init__(self, db_path: str):
        self.db_path = db_path.replace("sqlite:///", "").replace("sqlite://", "")
        with self._conn() as c:
            c.execute(_CHECKINS_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def add(self, user_id: str, checkin_date: str, sleep_quality: str | None,
                  outdoor_temp: float | None, humidity: float | None) -> None:
        await asyncio.to_thread(
            self._add, user_id, checkin_date, sleep_quality, outdoor_temp, humidity
        )

    def _add(self, user_id: str, checkin_date: str, sleep_quality: str | None,
             outdoor_temp: float | None, humidity: float | None) -> None:
        # One check-in per user per night; a later report for the same date
        # overwrites the earlier one (last write wins).
        with self._conn() as c:
            c.execute(
                """INSERT INTO checkins
                   (user_id, checkin_date, sleep_quality, outdoor_temp, humidity, created_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(user_id, checkin_date) DO UPDATE SET
                     sleep_quality=excluded.sleep_quality,
                     outdoor_temp=excluded.outdoor_temp,
                     humidity=excluded.humidity,
                     created_at=excluded.created_at""",
                (user_id, checkin_date, sleep_quality, outdoor_temp, humidity,
                 datetime.now(timezone.utc).isoformat()),
            )

    async def list_for_user(self, user_id: str, limit: int = 30) -> list[dict]:
        return await asyncio.to_thread(self._list_for_user, user_id, limit)

    def _list_for_user(self, user_id: str, limit: int) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT checkin_date, sleep_quality, outdoor_temp, humidity
                   FROM checkins WHERE user_id=?
                   ORDER BY checkin_date DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [
            {
                "checkin_date": r["checkin_date"],
                "sleep_quality": r["sleep_quality"],
                "outdoor_temp": r["outdoor_temp"],
                "humidity": r["humidity"],
            }
            for r in rows
        ]
