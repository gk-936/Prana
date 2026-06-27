import asyncio
from unittest.mock import patch
from datetime import datetime
from framework.context.user import UserContext
from framework.tools.base import ToolRegistry
from prana.ai_tools.risk import get_risk, risk_tool


def _fake_result():
    return {
        "ccri": 72.3, "risk_level": "HIGH", "ndt": 34.1,
        "rds": {"rds_mid": 150.0, "consecutive_nights": 3, "rds_low": 140, "rds_high": 160},
        "timestamp": datetime(2026, 6, 26, 21, 0), "alert_message": "Stay cool tonight.",
    }


def test_get_risk_returns_trimmed_real_keys():
    ctx = UserContext(user_id="u1", metadata={"lat": 13.08, "lon": 80.27,
                                              "location_name": "Chennai"})
    with patch("prana.ai_tools.risk.PRANASystem") as MockSys:
        MockSys.return_value.update_all.return_value = _fake_result()
        out = get_risk(ctx=ctx)
    assert out["ccri"] == 72.3 and out["risk_level"] == "HIGH"
    assert out["rds_mid"] == 150.0 and out["consecutive_nights"] == 3
    assert out["as_of"] == "2026-06-26T21:00:00"


def test_get_risk_tool_via_registry():
    reg = ToolRegistry(); reg.register(risk_tool)
    ctx = UserContext(user_id="u1", metadata={"lat": 13.08, "lon": 80.27})
    with patch("prana.ai_tools.risk.PRANASystem") as MockSys:
        MockSys.return_value.update_all.return_value = _fake_result()
        res = asyncio.run(reg.execute("get_risk", {}, ctx))
    assert res.ok and res.data["risk_level"] == "HIGH"
