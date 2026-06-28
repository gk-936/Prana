"""JSON-based persistence for prototype phase."""
import json
from datetime import datetime, date
from pathlib import Path
from typing import List


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _location_key(lat: float, lon: float) -> str:
    return f"{lat:.4f}_{lon:.4f}"


def _location_path(lat: float, lon: float) -> Path:
    return DATA_DIR / f"{_location_key(lat, lon)}.json"


def load_nighttime_temps(lat: float, lon: float) -> List[dict]:
    path = _location_path(lat, lon)
    if not path.exists():
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        temps = data.get("nighttime_temps", [])
        for t in temps:
            t["date"] = datetime.strptime(t["date"], "%Y-%m-%d").date()
        return temps
    except (json.JSONDecodeError, KeyError, ValueError):
        return []


def save_nighttime_temps(lat: float, lon: float, temps: List[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _location_path(lat, lon)
    serialized = []
    for t in temps:
        d = t["date"]
        if isinstance(d, date):
            d = d.isoformat()
        entry = {"date": d, "temp": t["temp"]}
        # Preserve humidity when present so wet-bulb scoring survives a reload
        if t.get("humidity") is not None:
            entry["humidity"] = t["humidity"]
        serialized.append(entry)
    payload = {
        "nighttime_temps": serialized,
        "last_updated": datetime.now().isoformat(),
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
