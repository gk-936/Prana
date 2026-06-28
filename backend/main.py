"""FastAPI backend for the PRANA mobile app."""

import os
import time
from collections import defaultdict
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.logger import get_logger

logger = get_logger("api")

from prana.config import OPENAQ_API_KEY, OPENWEATHER_API_KEY, UPDATE_INTERVAL  # noqa: E402
from prana.config import RDS_NIGHTTIME_THRESHOLD  # noqa: E402
from prana.prana_system import PRANASystem  # noqa: E402
from backend.database import load_nighttime_temps, save_nighttime_temps  # noqa: E402
from prana.bot.bootstrap import build_repo, build_checkin_repo  # noqa: E402
from prana.personalization import personalize_offset  # noqa: E402
from framework.context.user import UserContext  # noqa: E402
from prana.config import WHATSAPP_BOT_NUMBER  # noqa: E402

user_repo = build_repo()
checkin_repo = build_checkin_repo()


app = FastAPI(
    title="PRANA API",
    description="Backend API for PRANA climate risk results and mobile dashboard data.",
    version="0.1.0",
)

_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from prana.bot.whatsapp_webhook import router as whatsapp_router  # noqa: E402
app.include_router(whatsapp_router)


# ---------------------------------------------------------------------------
# Simple in-memory rate limiter
# ---------------------------------------------------------------------------

_RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
_window_store: dict = defaultdict(list)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _window_store[client_ip]
    cutoff = now - 60
    window[:] = [t for t in window if t > cutoff]
    if len(window) >= _RATE_LIMIT:
        logger.warning("Rate limit hit for %s", client_ip)
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again in a minute."},
        )
    window.append(now)
    return await call_next(request)


class RiskRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="User latitude.")
    lon: float = Field(..., ge=-180, le=180, description="User longitude.")
    location_name: str = Field("Current location", min_length=1, max_length=120)
    urban_heat_offset: float = Field(
        3.0,
        ge=0,
        le=8,
        description="Ward-level urban heat island offset in Celsius.",
    )
    sleep_checkin: Optional[dict] = Field(
        None, description="Structured sleep check-in from WhatsApp."
    )
    onboarding_data: Optional[dict] = Field(
        None, description="Home profile: {ac: bool, roof_material: str, floor_level: str}"
    )
    user_id: Optional[str] = Field(
        None,
        description="If provided, the user's stored sleep check-ins personalise "
                    "the RDS indoor-offset estimate. Omit for population-only scoring.",
    )


class RiskResponse(BaseModel):
    result: Dict[str, Any]
    calculation_log: str

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


class HomeProfile(BaseModel):
    ac: bool
    roof_material: str
    floor_level: str
    fan: bool = False
    windows_open: bool = False
    occupants: int = Field(1, ge=1, le=10, description="People sharing the sleeping room.")


class CheckinRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    sleep_quality: str = Field(
        ..., description="good | moderate | poor (or comfortable/warm/too_hot)."
    )
    outdoor_temp: Optional[float] = Field(
        None, ge=-30, le=60, description="Outdoor nighttime temp for the reported night (C)."
    )
    humidity: Optional[float] = Field(None, ge=0, le=100)
    checkin_date: Optional[str] = Field(
        None, description="ISO date (YYYY-MM-DD). Defaults to today (UTC)."
    )


class CheckinResponse(BaseModel):
    ok: bool
    user_id: str
    checkin_date: str
    n_checkins: int


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


@app.get("/health")
def health() -> Dict[str, Any]:
    """Return backend status for app and deployment checks."""
    return {
        "status": "ok",
        "service": "prana-api",
        "update_interval_hours": UPDATE_INTERVAL,
        "weather_provider": "open-meteo",
        "air_quality_provider": "open-meteo-cams",
        "openweather_fallback_configured": bool(OPENWEATHER_API_KEY),
        "openaq_configured": bool(OPENAQ_API_KEY),
    }


@app.post("/risk/current", response_model=RiskResponse)
async def calculate_current_risk(payload: RiskRequest) -> RiskResponse:
    """Calculate current PRANA climate risk metrics for a user-selected location.

    When `user_id` is supplied and that user has stored sleep check-ins, the RDS
    indoor-offset is personalised from those check-ins (Bayesian shrinkage from
    the onboarding prior). Otherwise scoring is population-only, exactly as before.
    """
    personalization = None
    if payload.user_id:
        checkins = await checkin_repo.list_for_user(payload.user_id, limit=30)
        if checkins:
            prior_mean = _onboarding_prior_mean(payload.onboarding_data)
            prior_sd = _onboarding_prior_sd(payload.onboarding_data)
            post = personalize_offset(prior_mean, prior_sd, checkins, RDS_NIGHTTIME_THRESHOLD)
            personalization = {"offset": post.mean, "band": post.sd, "n_checkins": post.n_checkins}

    result, logs = await run_in_threadpool(_run_prana_pipeline, payload, personalization)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not calculate risk. Check coordinates and upstream services.",
        )

    return RiskResponse(result=_serialize_result(result), calculation_log=logs)


@app.post("/checkin", response_model=CheckinResponse)
async def record_checkin(payload: CheckinRequest) -> CheckinResponse:
    """Record a nightly sleep check-in. These accumulate as the evidence that
    personalises a user's RDS indoor-offset over time."""
    checkin_date = payload.checkin_date or datetime.utcnow().date().isoformat()
    await checkin_repo.add(
        user_id=payload.user_id,
        checkin_date=checkin_date,
        sleep_quality=payload.sleep_quality,
        outdoor_temp=payload.outdoor_temp,
        humidity=payload.humidity,
    )
    stored = await checkin_repo.list_for_user(payload.user_id, limit=1000)
    return CheckinResponse(
        ok=True, user_id=payload.user_id, checkin_date=checkin_date,
        n_checkins=len(stored),
    )


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


def _onboarding_prior_mean(onboarding_data) -> float:
    """Prior mean for personalization = the onboarding-derived indoor offset."""
    from prana.rds_calculator import RDSCalculator
    return RDSCalculator.compute_onboarding_temp_offset(onboarding_data)


def _onboarding_prior_sd(onboarding_data) -> float:
    """Prior SD for personalization = the onboarding offset band half-width."""
    from prana.rds_calculator import RDSCalculator
    return RDSCalculator.compute_band_width(onboarding_data)


def _run_prana_pipeline(payload: RiskRequest, personalization=None):
    # Load persisted nighttime temps for this location
    past_temps = load_nighttime_temps(payload.lat, payload.lon)

    prana = PRANASystem(
        api_key=OPENWEATHER_API_KEY,
        location_name=payload.location_name,
        urban_heat_offset=payload.urban_heat_offset,
        openaq_api_key=OPENAQ_API_KEY,
        onboarding_data=payload.onboarding_data,
    )

    # Seed RDS calculator with persisted history
    if past_temps:
        prana.rds_calculator.nighttime_temps = past_temps

    stdout = StringIO()
    with redirect_stdout(stdout):
        result = prana.update_all(
            payload.lat, payload.lon,
            sleep_checkin=payload.sleep_checkin,
            personalization=personalization,
        )

    # Persist updated nighttime temps for next call
    if result:
        save_nighttime_temps(payload.lat, payload.lon, prana.rds_calculator.nighttime_temps)

    return result, stdout.getvalue()


def _serialize_result(result: dict) -> dict:
    """Recursively convert datetime objects to ISO strings for JSON serialization."""
    if isinstance(result, dict):
        return {k: _serialize_result(v) for k, v in result.items()}
    if isinstance(result, list):
        return [_serialize_result(v) for v in result]
    if isinstance(result, datetime):
        return result.isoformat()
    return result
