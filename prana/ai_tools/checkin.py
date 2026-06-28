"""PRANA's record_checkin tool — lets the WhatsApp agent log a sleep check-in.

A check-in is the evidence the personalization layer consumes: it nudges the
user's learned indoor-offset toward their real conditions over time. The agent
extracts the sleep-quality label from the conversation; this tool derives the
user identity from context, captures the outdoor nighttime temperature so the
observation is usable, and persists it.
"""
from __future__ import annotations

from datetime import datetime

from framework.context.user import UserContext
from framework.tools.base import Tool
from framework.persistence.sqlite import SQLiteCheckinRepository
from prana.config import DATABASE_URL, OPENAQ_API_KEY, OPENWEATHER_API_KEY
from prana.prana_system import PRANASystem

# Map free-text/structured sleep descriptions to the canonical labels the
# personalization pipeline understands.
_QUALITY_ALIASES = {
    "good": "good", "well": "good", "fine": "good", "comfortable": "good",
    "cool": "good", "cool_enough": "good", "ok": "moderate", "okay": "moderate",
    "moderate": "moderate", "warm": "moderate", "warm_manageable": "moderate",
    "average": "moderate", "poor": "poor", "bad": "poor", "hot": "poor",
    "too_hot": "poor", "terrible": "poor", "couldnt_sleep": "poor",
    "cooling_unavailable": "poor",
}


def _normalize_quality(raw: str) -> str | None:
    key = str(raw).strip().lower().replace(" ", "_").replace("'", "")
    return _QUALITY_ALIASES.get(key)


async def record_checkin(*, ctx: UserContext, sleep_quality: str) -> dict:
    """Record a sleep check-in for the current user.

    Args:
        sleep_quality: how the user said they slept (e.g. "good", "warm",
                       "too hot"). Normalised to good | moderate | poor.
    """
    quality = _normalize_quality(sleep_quality)
    if quality is None:
        return {
            "recorded": False,
            "error": (
                f"Could not interpret sleep quality '{sleep_quality}'. "
                "Expected something like good, warm, or too hot."
            ),
        }

    meta = ctx.metadata
    lat = meta.get("lat")
    lon = meta.get("lon")

    # Capture the outdoor nighttime temperature/humidity so the observation is
    # usable by the personalization pipeline. If weather is unavailable, the
    # check-in is still stored (quality only); the pipeline will skip it for
    # offset inference but it remains a record.
    outdoor_temp = None
    humidity = None
    if lat is not None and lon is not None:
        try:
            system = PRANASystem(
                api_key=OPENWEATHER_API_KEY,
                location_name=meta.get("location_name", "Current location"),
                urban_heat_offset=meta.get("urban_heat_offset"),
                openaq_api_key=OPENAQ_API_KEY,
                onboarding_data=meta.get("onboarding"),
            )
            forecast = system.data_fetcher.get_forecast(lat, lon)
            conditions = system.rds_calculator.estimate_nighttime_conditions_from_forecast(
                forecast
            )
            if conditions:
                outdoor_temp = conditions.get("temp")
                humidity = conditions.get("humidity")
        except Exception:  # noqa: BLE001 - weather is best-effort, never block the check-in
            pass

    checkin_date = datetime.utcnow().date().isoformat()
    repo = SQLiteCheckinRepository(DATABASE_URL)
    await repo.add(
        user_id=ctx.user_id,
        checkin_date=checkin_date,
        sleep_quality=quality,
        outdoor_temp=outdoor_temp,
        humidity=humidity,
    )
    stored = await repo.list_for_user(ctx.user_id, limit=1000)
    return {
        "recorded": True,
        "sleep_quality": quality,
        "checkin_date": checkin_date,
        "n_checkins": len(stored),
        "note": (
            "Recorded. PRANA will use this to personalise your recovery score "
            "over the next few check-ins."
        ),
    }


record_checkin_tool = Tool(
    name="record_checkin",
    description=(
        "Record how the user slept last night when they report it (e.g. 'slept "
        "badly, too hot', 'slept fine'). Normalises to good/moderate/poor and "
        "stores it so PRANA can personalise the user's sleep-recovery (RDS) score "
        "over time. Call this whenever the user describes their sleep or replies "
        "to a sleep check-in prompt."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sleep_quality": {
                "type": "string",
                "description": "How the user said they slept: good, moderate/warm, or poor/too hot.",
            }
        },
        "required": ["sleep_quality"],
    },
    fn=record_checkin,
    required_permission=None,
)
