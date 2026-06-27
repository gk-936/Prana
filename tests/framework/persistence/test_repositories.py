import asyncio
import pytest
from framework.context.user import UserContext
from framework.persistence.memory import InMemoryUserRepository
from framework.persistence.sqlite import SQLiteUserRepository


def _user():
    return UserContext(user_id="u1", phone="+919900", locale="ta",
                       metadata={"lat": 13.08, "lon": 80.27, "location_name": "Chennai"})


@pytest.mark.parametrize("make_repo", [
    lambda tmp: InMemoryUserRepository(),
    lambda tmp: SQLiteUserRepository(str(tmp / "t.db")),
])
def test_upsert_then_get_by_phone(make_repo, tmp_path):
    repo = make_repo(tmp_path)
    async def go():
        await repo.upsert(_user())
        u = await repo.get_by_phone("+919900")
        assert u is not None and u.user_id == "u1" and u.locale == "ta"
        assert u.metadata["lat"] == 13.08
    asyncio.run(go())


@pytest.mark.parametrize("make_repo", [
    lambda tmp: InMemoryUserRepository(),
    lambda tmp: SQLiteUserRepository(str(tmp / "t.db")),
])
def test_get_missing_returns_none(make_repo, tmp_path):
    repo = make_repo(tmp_path)
    assert asyncio.run(repo.get_by_phone("+000")) is None


def test_sqlite_upsert_is_idempotent(tmp_path):
    repo = SQLiteUserRepository(str(tmp_path / "t.db"))
    async def go():
        await repo.upsert(_user())
        await repo.upsert(_user())  # second upsert must not raise
        u = await repo.get("u1")
        assert u.user_id == "u1"
    asyncio.run(go())


def test_sqlite_strips_url_prefix(tmp_path):
    repo = SQLiteUserRepository(f"sqlite:///{tmp_path}/url.db")
    asyncio.run(repo.upsert(_user()))
    assert asyncio.run(repo.get("u1")).user_id == "u1"


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
