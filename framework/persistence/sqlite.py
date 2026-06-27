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
