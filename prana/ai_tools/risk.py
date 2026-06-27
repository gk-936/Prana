"""PRANA's get_risk tool — wraps the deterministic scoring engine for the agent."""
from __future__ import annotations

from framework.context.user import UserContext
from framework.tools.base import Tool
from prana.config import OPENAQ_API_KEY, OPENWEATHER_API_KEY
from prana.prana_system import PRANASystem


def get_risk(*, ctx: UserContext) -> dict:
    meta = ctx.metadata
    system = PRANASystem(
        api_key=OPENWEATHER_API_KEY,
        location_name=meta.get("location_name", "Current location"),
        # None is intentional: lets PRANASystem look up the real per-location
        # UHI offset via lookup_uhi_offset instead of using a hardcoded default.
        urban_heat_offset=meta.get("urban_heat_offset"),
        openaq_api_key=OPENAQ_API_KEY,
        onboarding_data=meta.get("onboarding"),
    )
    result = system.update_all(meta["lat"], meta["lon"])
    if not result:
        return {"error": "Risk data is temporarily unavailable."}
    rds = result["rds"]
    ts = result["timestamp"]
    return {
        "ccri": result["ccri"],
        "risk_level": result["risk_level"],
        "ndt": result["ndt"],
        "rds_mid": rds["rds_mid"],
        "consecutive_nights": rds["consecutive_nights"],
        "alert_message": result["alert_message"],
        "as_of": ts.isoformat() if hasattr(ts, "isoformat") else ts,
    }


risk_tool = Tool(
    name="get_risk",
    description=(
        "Get the user's current compound climate risk (heat + pollution + sleep "
        "recovery). Call this whenever the user asks about their risk, heat, air "
        "quality, sleep, or why an alert was sent."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    fn=get_risk,
    required_permission=None,
)
