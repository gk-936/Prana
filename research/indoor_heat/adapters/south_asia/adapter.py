"""Adapter encoding South Asia dataset (Figshare 12546368) per-site quirks."""
from __future__ import annotations
import re
from pathlib import Path
import pandas as pd

_SITE_FILE_PREFIX = {
    "delhi": "Delhi", "dhaka": "Dhaka", "faisalabad": "Faisalabad",
    "jalna": "Jalna", "yavatmal": "Yavatmal",
}

# Canonical roof categories. Raw labels (lowercased, stripped) -> canonical.
_ROOF_CANON = {
    "tin": "tin", "metal": "tin", "asbestos": "tin", "gi sheet": "tin",
    "concrete": "concrete", "rcc": "concrete", "cement": "concrete",
    "brick": "brick",
    "stone": "stone",
}
_FLOOR_CANON_TRUE = {"yes", "top", "top floor", "1", "true"}

class SouthAsiaAdapter:
    name = "south_asia"
    site_names = ["delhi", "dhaka", "faisalabad", "jalna", "yavatmal"]
    indoor_dash_is_dmy = True   # indoor files: dash-format is DD-MM-YYYY
    aws_dash_is_dmy = False     # AWS files: dash-format is MM-DD-YYYY (opposite!)

    def __init__(self, raw_dir: str | Path = "data/raw"):
        self.raw_dir = Path(raw_dir)

    def indoor_path(self, site: str) -> Path:
        return self.raw_dir / f"{_SITE_FILE_PREFIX[site]} Indoor Data.csv"

    def aws_path(self, site: str) -> Path:
        return self.raw_dir / f"{_SITE_FILE_PREFIX[site]} AWS Data.csv"

    def housing_path(self, site: str) -> Path:
        return self.raw_dir / f"{_SITE_FILE_PREFIX[site]} Housing Structure Data.csv"

    def roof_map(self, site: str) -> dict:
        return dict(_ROOF_CANON)

    def floor_map(self, site: str) -> dict:
        # canonical floor_level: 'top' if the raw value indicates top floor, else 'other'
        return {v: "top" for v in _FLOOR_CANON_TRUE}

    def column_map(self, site: str) -> dict:
        # Harmonize AWS outdoor-temp column name to canonical 'outdoor_temp'.
        # Urban sites use Davis "Temp Out"; rural use generic "Air temperature".
        return {
            "Temp Out": "outdoor_temp",
            "Air temperature": "outdoor_temp",
            "Air Temperature": "outdoor_temp",
        }

    def repair_rows(self, raw: pd.DataFrame, kind: str) -> pd.DataFrame:
        """Repair Dhaka AWS '2016'-split corruption. No-op for other kinds/sites.

        Corruption pattern: year '2016' split so '201' is stuck on the date
        column and a leading '6' is stuck onto the Time column, e.g.
        date='06-01-201', time='6  1:00:00 AM'. Reconstruct by moving the
        leading digit back. A legitimate midnight reading can superficially
        match, so only repair rows where the date column ends with '-201'.
        """
        if kind != "aws" or "Time" not in raw.columns:
            return raw
        df = raw.copy()
        date_col = df.columns[0]
        mask = df[date_col].astype(str).str.endswith("-201")
        if not mask.any():
            return df
        pat = re.compile(r"^(\d)\s+(\d{1,2}:\d{2}.*)$")
        def fix(row):
            d = str(row[date_col])
            t = str(row["Time"])
            m = pat.match(t)
            if d.endswith("-201") and m:
                row[date_col] = d + m.group(1)   # reattach split digit -> '...2016'
                row["Time"] = m.group(2)
            return row
        df.loc[mask] = df.loc[mask].apply(fix, axis=1)
        return df
