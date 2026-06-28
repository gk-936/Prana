"""
PRANA preflight check — verifies the RDS + onboarding integration is wired
correctly across config, calculator, system, and API schema.

Usage:
    python scripts/preflight_check.py            # offline checks only
    python scripts/preflight_check.py --live      # also hit a running backend

The --live mode expects the backend running on http://127.0.0.1:8000
(start it with scripts/start_backend.ps1 in another terminal).

Exit code 0 = all checks passed, 1 = at least one failed.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

# Ensure project root is importable when run as `python scripts/preflight_check.py`
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "[PASS]"
FAIL = "[FAIL]"
_failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    line = f"  {PASS if cond else FAIL} {name}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if not cond:
        _failures.append(name)


def section(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def main(live: bool = False) -> int:
    section("1. IMPORT CHAIN")
    try:
        from prana.config import (
            RDS_USE_WET_BULB, RDS_NIGHTTIME_THRESHOLD, RDS_NIGHTTIME_WETBULB_THRESHOLD,
            RDS_ONBOARDING_FAN_OFFSET, RDS_ONBOARDING_WINDOW_OFFSET,
            RDS_ONBOARDING_PER_EXTRA_OCCUPANT_OFFSET, RDS_AC_EXTRA_BAND_WIDTH,
        )
        check("prana.config imports new RDS constants", True)
    except Exception as e:  # noqa: BLE001
        check("prana.config imports new RDS constants", False, str(e))
        return _finish()

    try:
        from prana.rds_calculator import RDSCalculator, _stull_wet_bulb
        check("prana.rds_calculator imports", True)
    except Exception as e:  # noqa: BLE001
        check("prana.rds_calculator imports", False, str(e))
        return _finish()

    try:
        from prana.prana_system import PRANASystem  # noqa: F401
        check("prana.prana_system imports", True)
    except Exception as e:  # noqa: BLE001
        check("prana.prana_system imports", False, str(e))

    try:
        from backend.main import app, HomeProfile, RiskRequest  # noqa: F401
        check("backend.main (FastAPI app + schemas) imports", True)
    except Exception as e:  # noqa: BLE001
        check("backend.main imports", False, str(e))

    section("2. ONBOARDING OFFSET WIRING")
    from prana.rds_calculator import RDSCalculator

    legacy = {'ac': False, 'roof_material': 'tin', 'floor_level': 'top'}
    full = {'ac': False, 'roof_material': 'tin', 'floor_level': 'top',
            'fan': True, 'windows_open': True, 'occupants': 3}
    off_legacy = RDSCalculator.compute_onboarding_temp_offset(legacy)
    off_full = RDSCalculator.compute_onboarding_temp_offset(full)
    check("legacy profile offset == +3.5C (tin+top)", off_legacy == 3.5, f"{off_legacy}")
    check("full profile offset == +1.0C (tin+top-fan-win+2ppl)", off_full == 1.0, f"{off_full}")
    check("fan/window/occupants actually change the offset", off_full != off_legacy)

    b_default = RDSCalculator.compute_band_width({'ac': False})
    b_ac = RDSCalculator.compute_band_width({'ac': True})
    check("AC widens the uncertainty band", b_ac > b_default, f"{b_default} -> {b_ac}")

    section("3. HUMIDITY-AWARE RDS (the core fix)")
    def rds_mid(onb, nights):
        c = RDSCalculator(onb)
        today = datetime.now().date()
        for da, t, h in nights:
            c.add_night_temperature(t, date=today - timedelta(days=da), humidity=h)
        return c.calculate_rds()['rds_mid']

    base = {'roof_material': 'concrete', 'floor_level': 'other'}
    chennai = rds_mid(base, [(2, 32.0, 80), (1, 32.0, 80), (0, 32.0, 80)])
    karachi = rds_mid(base, [(2, 32.0, 40), (1, 32.0, 40), (0, 32.0, 40)])
    check("humid city scores higher than dry city at same temp",
          chennai > karachi, f"chennai={chennai} karachi={karachi}")

    dry_hot = rds_mid(base, [(0, 36.0, 40)])
    check("dry heat still scored (36C/40% not zeroed out)", dry_hot > 0, f"rds={dry_hot}")

    nofan = rds_mid(base, [(2, 34.0, 75), (1, 34.0, 75), (0, 34.0, 75)])
    fan = rds_mid({**base, 'fan': True}, [(2, 34.0, 75), (1, 34.0, 75), (0, 34.0, 75)])
    check("fan reduces RDS", fan < nofan, f"fan={fan} nofan={nofan}")

    section("4. RDS BAND DICT CONTRACT (frontend depends on this shape)")
    c = RDSCalculator(full)
    today = datetime.now().date()
    for da, t, h in [(2, 35.0, 78), (1, 35.0, 78), (0, 35.0, 78)]:
        c.add_night_temperature(t, date=today - timedelta(days=da), humidity=h)
    d = c.calculate_rds()
    for key in ('rds_low', 'rds_mid', 'rds_high', 'consecutive_nights'):
        check(f"calculate_rds() returns '{key}'", key in d)
    check("band ordering low <= mid <= high",
          d['rds_low'] <= d['rds_mid'] <= d['rds_high'],
          f"{d['rds_low']}/{d['rds_mid']}/{d['rds_high']}")

    section("5. API SCHEMA ACCEPTS NEW FIELDS")
    from backend.main import HomeProfile, RiskRequest
    hp = HomeProfile(ac=False, roof_material='tin', floor_level='top',
                     fan=True, windows_open=True, occupants=3)
    dumped = hp.model_dump()
    check("HomeProfile carries fan/windows_open/occupants",
          all(k in dumped for k in ('fan', 'windows_open', 'occupants')),
          str(dumped))
    # Legacy payload (no new fields) must still validate via defaults
    hp_legacy = HomeProfile(ac=True, roof_material='concrete', floor_level='ground')
    check("HomeProfile legacy payload still valid (defaults applied)",
          hp_legacy.fan is False and hp_legacy.occupants == 1)
    rr = RiskRequest(lat=13.08, lon=80.27, location_name='Chennai',
                     onboarding_data=dumped)
    check("RiskRequest accepts onboarding_data", rr.onboarding_data == dumped)
    rr_pers = RiskRequest(lat=13.08, lon=80.27, location_name='Chennai', user_id='u1')
    check("RiskRequest accepts user_id (personalization trigger)", rr_pers.user_id == 'u1')

    section("6. PERSONALIZATION LOOP (offline)")
    from prana.personalization import personalize_offset, update_posterior
    from prana.config import RDS_NIGHTTIME_THRESHOLD as THR

    # Onboarding prior: concrete/ground -> offset 0, band 2.0
    onb = {'roof_material': 'concrete', 'floor_level': 'other'}
    prior_mean = RDSCalculator.compute_onboarding_temp_offset(onb)
    prior_sd = RDSCalculator.compute_band_width(onb)

    # No check-ins -> prior unchanged
    p0 = personalize_offset(prior_mean, prior_sd, [], THR)
    check("no check-ins returns prior offset", p0.mean == prior_mean and p0.n_checkins == 0)

    # 6 poor-sleep check-ins at a modest outdoor temp -> learned offset rises
    poor = [{'outdoor_temp': 29.0, 'sleep_quality': 'poor'} for _ in range(6)]
    p_hot = personalize_offset(prior_mean, prior_sd, poor, THR)
    check("repeated poor sleep raises learned offset", p_hot.mean > prior_mean,
          f"prior={prior_mean} learned={p_hot.mean}")
    check("posterior band narrows with evidence", p_hot.sd < prior_sd,
          f"{prior_sd} -> {p_hot.sd}")

    # Feed the learned offset into RDS exactly as the backend does
    cc = RDSCalculator(onb)
    today2 = datetime.now().date()
    for da, t, h in [(2, 33.0, 72), (1, 33.0, 72), (0, 33.0, 72)]:
        cc.add_night_temperature(t, date=today2 - timedelta(days=da), humidity=h)
    pop_rds = cc.calculate_rds()
    pers_rds = cc.calculate_rds(personalized_offset=p_hot.mean, personalized_band=p_hot.sd)
    check("population RDS not flagged personalized", pop_rds['personalized'] is False)
    check("personalized RDS flagged", pers_rds['personalized'] is True)
    check("hot-running user scored higher than population",
          pers_rds['rds_mid'] > pop_rds['rds_mid'],
          f"pop={pop_rds['rds_mid']} pers={pers_rds['rds_mid']}")

    # Symmetric: consistent good sleep at high temp -> lower than population
    good = [{'outdoor_temp': 34.0, 'sleep_quality': 'good'} for _ in range(6)]
    p_cool = personalize_offset(prior_mean, prior_sd, good, THR)
    pers_cool = cc.calculate_rds(personalized_offset=p_cool.mean, personalized_band=p_cool.sd)
    check("good-sleeper scored lower than population",
          pers_cool['rds_mid'] < pop_rds['rds_mid'],
          f"pop={pop_rds['rds_mid']} cool={pers_cool['rds_mid']}")

    if live:
        section("7. LIVE BACKEND (end-to-end through Open-Meteo)")
        try:
            import requests
            base_payload = {
                "lat": 13.0827, "lon": 80.2707, "location_name": "Chennai",
                "urban_heat_offset": 3.0,
                "onboarding_data": {
                    "ac": False, "roof_material": "concrete", "floor_level": "ground",
                },
            }
            r = requests.post("http://127.0.0.1:8000/risk/current",
                              json=base_payload, timeout=30)
            check("POST /risk/current returns 200", r.status_code == 200,
                  f"status={r.status_code}")
            pop_mid = None
            if r.status_code == 200:
                res = r.json().get("result", {})
                rds = res.get("rds")
                check("response includes rds band dict",
                      isinstance(rds, dict) and 'rds_mid' in rds, str(rds)[:80])
                check("response includes ccri + risk_level",
                      res.get("ccri") is not None and res.get("risk_level"))
                check("population call not flagged personalized",
                      isinstance(rds, dict) and rds.get('personalized') is False)
                pop_mid = rds.get('rds_mid') if isinstance(rds, dict) else None

            # Record poor-sleep check-ins for a throwaway user, then request risk
            # with user_id and confirm the loop personalizes end to end over HTTP.
            import time as _t
            uid = f"preflight_{int(_t.time())}"
            for d in ("2026-06-25", "2026-06-26", "2026-06-27"):
                requests.post("http://127.0.0.1:8000/checkin", timeout=10, json={
                    "user_id": uid, "sleep_quality": "poor",
                    "outdoor_temp": 29.0, "checkin_date": d,
                })
            pr = requests.post("http://127.0.0.1:8000/risk/current", timeout=30, json={
                **base_payload, "user_id": uid,
            })
            check("personalized POST /risk/current returns 200", pr.status_code == 200,
                  f"status={pr.status_code}")
            if pr.status_code == 200:
                prds = pr.json().get("result", {}).get("rds", {})
                check("personalized response flagged",
                      isinstance(prds, dict) and prds.get('personalized') is True,
                      str(prds)[:80])
        except Exception as e:  # noqa: BLE001
            check("live backend reachable", False, str(e))

    return _finish()


def _finish() -> int:
    section("RESULT")
    if _failures:
        print(f"  {FAIL} {len(_failures)} check(s) failed:")
        for f in _failures:
            print(f"        - {f}")
        return 1
    print(f"  {PASS} All checks passed. RDS + onboarding integration is wired correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main(live="--live" in sys.argv))
