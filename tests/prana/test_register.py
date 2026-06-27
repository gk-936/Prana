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
