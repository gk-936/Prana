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
# Discovered raw labels across all 5 real sites (see README for the full
# audit): tin/metal sheeting -> tin; poured concrete/cement/RCC -> concrete;
# fired-clay products (brick, roof tiles) -> brick; stone slabs -> stone.
# 'floor on top'/'floor above' is a sentinel meaning "no roof here, another
# storey sits on top" (not a roof material) and 'straw'/thatch are a
# genuinely-other minor category (<2% of rows) -- both intentionally left
# unmapped -> None.
_ROOF_CANON = {
    "tin": "tin", "metal": "tin", "asbestos": "tin", "gi sheet": "tin",
    "tin sheet": "tin", "tin sheet + plastic": "tin", "tin roof": "tin",
    "concrete": "concrete", "rcc": "concrete", "cement": "concrete",
    "concrete + cement": "concrete",
    "brick": "brick", "bricks + cement": "brick",
    "double tile": "brick", "single tile": "brick", "tile roof": "brick",
    "stone": "stone", "stone slab + ext": "stone", "stone slabs + cement": "stone",
}
_FLOOR_CANON_TRUE = {"yes", "top", "top floor", "1", "true"}

# Per-site date-format overrides discovered from the real data (see README).
# Confirmed via dates.parse_with_continuity (negative-jump detection) against
# the actual files, NOT assumed from documentation -- Delhi and Jalna's
# indoor dash-dates turned out to be month-first (MM-DD), contradicting the
# project's prior assumption that ALL indoor files were day-first (DD-MM).
# Dhaka/Faisalabad/Yavatmal indoor dash-dates ARE day-first as originally
# assumed. Separately, the rural AWS files (Jalna, Yavatmal) are day-first
# (DD-MM) instead of the urban-site month-first (MM-DD) convention.
_INDOOR_DASH_IS_DMY_OVERRIDE = {"delhi": False, "jalna": False}
_AWS_DASH_IS_DMY_OVERRIDE = {"jalna": True, "yavatmal": True}
# Sites whose indoor date STRINGS are unreliable (Faisalabad flips DD-MM/MM-DD
# mid-file; Yavatmal repeats dates across midnight). For these the date is
# reconstructed from the 144-counter block structure instead of trusting the
# dash convention -- see dates.reconstruct_block_dates.
_INDOOR_RECONSTRUCT_DATES = {"faisalabad", "yavatmal"}
_HOUSING_ENCODING_OVERRIDE = {"yavatmal": "latin-1"}
_AWS_ENCODING_OVERRIDE = {"jalna": "latin-1"}

class SouthAsiaAdapter:
    name = "south_asia"
    site_names = ["delhi", "dhaka", "faisalabad", "jalna", "yavatmal"]
    indoor_dash_is_dmy = True   # indoor files: dash-format is DD-MM-YYYY (default; Jalna overridden)
    aws_dash_is_dmy = False     # AWS files: dash-format is MM-DD-YYYY (default; Jalna/Yavatmal overridden)

    def __init__(self, raw_dir: str | Path = "data/raw"):
        self.raw_dir = Path(raw_dir)

    def indoor_path(self, site: str) -> Path:
        return self.raw_dir / f"{_SITE_FILE_PREFIX[site]} Indoor Data.csv"

    def aws_path(self, site: str) -> Path:
        return self.raw_dir / f"{_SITE_FILE_PREFIX[site]} AWS Data.csv"

    def housing_path(self, site: str) -> Path:
        return self.raw_dir / f"{_SITE_FILE_PREFIX[site]} Housing Structure Data.csv"

    def indoor_dash_is_dmy_for(self, site: str) -> bool:
        return _INDOOR_DASH_IS_DMY_OVERRIDE.get(site, self.indoor_dash_is_dmy)

    def indoor_reconstruct_dates(self, site: str) -> bool:
        return site in _INDOOR_RECONSTRUCT_DATES

    def aws_dash_is_dmy_for(self, site: str) -> bool:
        return _AWS_DASH_IS_DMY_OVERRIDE.get(site, self.aws_dash_is_dmy)

    def housing_encoding(self, site: str) -> str:
        return _HOUSING_ENCODING_OVERRIDE.get(site, "utf-8")

    def aws_encoding(self, site: str) -> str:
        return _AWS_ENCODING_OVERRIDE.get(site, "utf-8")

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
        """Repair known per-row corruption in AWS/indoor logger exports.

        - kind='aws': Dhaka AWS '2016'-split corruption. Year '2016' split so
          '201' is stuck on the date column and a leading '6' is stuck onto
          the Time column, e.g. date='06-01-201', time='6  1:00:00 AM'. This
          happens for BOTH dash-format dates (e.g. '06-01-201') and
          slash-format dates (e.g. '10/13/201'), so the corruption mask
          checks for a trailing '201' regardless of separator. Reconstruct
          by moving the leading digit back. A legitimate midnight reading
          can superficially match, so only repair rows where the date
          column ends with '201'.
        - kind='indoor': Jalna's logger occasionally mislabels an ENTIRE
          144-reading day-block with the wrong date (5 blocks dataset-wide):
          either the date string fails to advance at midnight and the whole
          block repeats the previous day's date, or it advances to the
          wrong date entirely (observed: a whole block stamped '01-01-2019'
          instead of '01-12-2019'). Detected using the '144\\n(10 Min)'
          intra-day reading counter, which is a reliable 1..144 cycle with
          no irregular jumps in the real data: whenever a block-starting row
          (counter resets to 1 right after a row with counter 144) has a
          date that isn't exactly one calendar day after the previous
          block's date, the entire block (all rows up to the next reset) is
          overwritten with the corrected date (previous block's date + 1,
          formatted to match that block's original separator style).
        No-op for other kind/site combinations.
        """
        if kind == "aws":
            return self._repair_aws_year_split(raw)
        if kind == "indoor":
            return self._repair_indoor_midnight_rollover(raw)
        return raw

    @staticmethod
    def _repair_aws_year_split(raw: pd.DataFrame) -> pd.DataFrame:
        if "Time" not in raw.columns:
            return raw
        df = raw.copy()
        date_col = df.columns[0]
        mask = df[date_col].astype(str).str.endswith("201")
        if not mask.any():
            return df
        pat = re.compile(r"^(\d)\s+(\d{1,2}:\d{2}.*)$")
        def fix(row):
            d = str(row[date_col])
            t = str(row["Time"])
            m = pat.match(t)
            if d.endswith("201") and m:
                row[date_col] = d + m.group(1)   # reattach split digit -> '...2016'
                row["Time"] = m.group(2)
            return row
        df.loc[mask] = df.loc[mask].apply(fix, axis=1)
        return df

    _COUNTER_COL = "144\n(10 Min)"

    @classmethod
    def _repair_indoor_midnight_rollover(cls, raw: pd.DataFrame) -> pd.DataFrame:
        if "Time" not in raw.columns or cls._COUNTER_COL not in raw.columns:
            return raw
        cols = list(raw.columns)
        time_idx = cols.index("Time")
        date_col = next(c for c in cols[: time_idx + 1]
                        if c != "Time" and c.lower() not in ("sr no", "sr no."))
        df = raw.copy()
        date_str = df[date_col].astype(str)
        counter = pd.to_numeric(df[cls._COUNTER_COL], errors="coerce")
        is_reset = (counter == 1) & (counter.shift(1) == 144)
        # Parse dash-format and slash-format rows in two vectorized batches
        # (dayfirst=False matches this site's MM-DD convention for both) --
        # a single mixed dash/slash Series can defeat pandas' format
        # inference, and per-row .map() is too slow at this dataset's scale.
        is_dash = date_str.str.contains("-")
        parsed = pd.Series(pd.NaT, index=date_str.index, dtype="datetime64[ns]")
        if is_dash.any():
            parsed.loc[is_dash] = pd.to_datetime(date_str[is_dash], dayfirst=False, errors="coerce")
        if (~is_dash).any():
            parsed.loc[~is_dash] = pd.to_datetime(date_str[~is_dash], dayfirst=False, errors="coerce")

        # block_id increments at every reset row (one block = one 144-row
        # logical day). Build a per-block summary (one row per block) and
        # walk it SEQUENTIALLY so each block's correctness is judged against
        # the PREVIOUS block's already-corrected date, not its stale raw
        # date -- a single vectorized comparison against shift(1) gives
        # false positives/negatives when consecutive blocks are both wrong
        # or when a correction shifts what the next block should be.
        block_id = is_reset.cumsum()
        block_first_idx = pd.Series(date_str.index, index=date_str.index)[is_reset | (block_id == 0)]
        block_starts = df.index[is_reset].tolist()
        if not block_starts:
            return df
        block_dates = parsed.loc[block_starts].dt.normalize().tolist()
        block_is_dash = is_dash.loc[block_starts].tolist()
        corrected = list(block_dates)
        changed = [False] * len(block_dates)
        for i in range(1, len(corrected)):
            expected_date = corrected[i - 1] + pd.Timedelta(days=1)
            if corrected[i] != expected_date:
                corrected[i] = expected_date
                changed[i] = True
        if not any(changed):
            return df
        block_id_to_pos = {bid: pos for pos, bid in enumerate(block_id.loc[block_starts])}
        for pos, is_changed in enumerate(changed):
            if not is_changed:
                continue
            bid = list(block_id_to_pos.keys())[pos]
            mask = block_id == bid
            new_date = corrected[pos]
            fmt = "%m-%d-%Y" if block_is_dash[pos] else "%m/%d/%Y"
            df.loc[mask, date_col] = new_date.strftime(fmt)
        return df
