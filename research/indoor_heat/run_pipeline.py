"""Wire adapter + core steps into per-site and merged datasets."""
from __future__ import annotations

import re
from pathlib import Path
import pandas as pd

from research.indoor_heat.core import outliers, aggregate, dates, harmonize, join, validate, merge
from research.indoor_heat.adapters.south_asia.adapter import SouthAsiaAdapter

def _normalize_logger_id(series: pd.Series) -> pd.Series:
    """Coerce a logger-id column to a comparable string form.

    Housing 'Logger ID'/'Serial no' columns are sometimes read as float64
    (when the column has trailing blank rows), yielding '10900693.0'
    instead of '10900693'. Strip any trailing '.0' so it matches the
    indoor-side logger_id strings derived from CSV header names.
    """
    s = series.astype(str).str.strip()
    return s.str.replace(r"\.0$", "", regex=True)

def _is_logger_col(name: str) -> bool:
    """Logger-id columns are purely numeric (optionally with a pandas dedup
    '.N' suffix or a trailing '(RH)' humidity marker stripped first)."""
    base = str(name).strip()
    if base.endswith("(RH)"):
        base = base[: -len("(RH)")].strip()
    base = re.sub(r"\.\d+$", "", base)
    return base.isdigit()

def _melt_indoor(raw: pd.DataFrame):
    """Wide indoor -> (long [raw_ts, logger_id, temp], raw_ts_series).

    Returns the melted long frame AND the raw timestamp string series in the
    original (pre-melt) row order. The raw series is a single, chronological
    per-row timeline (one row per 10-min interval, shared across all logger
    columns), which is the correct input for the date continuity check. The
    melted long series is NOT: it stacks every logger's full timeline
    end-to-end, so it resets backward at each logger boundary, and different
    loggers cover different date ranges, so even its unique values are not
    globally monotonic.

    Two shapes are supported:
    - Real data: leading 'Sr No', a date column (header literally says
      'DD/MM/YYYY' but the actual dash-format convention varies by site —
      see dates.parse_with_continuity), a 'Time' column, then metadata
      columns ('144\\n(10 Min)', 'Hours', 'Month', 'Season') before the
      actual logger-id columns (purely numeric names). The date + Time
      columns are combined into one timestamp string.
    - Synthetic/test data: a single leading timestamp column followed
      directly by logger columns (no metadata columns, non-numeric names).

    Drops logger columns suffixed '(RH)' (humidity).
    """
    cols = list(raw.columns)
    has_split_ts = "Time" in cols[:3]
    if has_split_ts:
        # Real data: 'Sr No', a date column, 'Time' (in some order within the
        # first 3 columns), then metadata columns, then logger columns.
        time_idx = cols.index("Time")
        lead_cols = cols[: time_idx + 1]
        date_col = next(c for c in lead_cols if c != "Time" and c.lower() not in ("sr no", "sr no."))
        time_col = "Time"
        raw_ts = raw[date_col].astype(str) + " " + raw[time_col].astype(str)
        candidate_cols = cols[time_idx + 1 :]
    else:
        ts_col = cols[0]
        raw_ts = raw[ts_col].astype(str)
        candidate_cols = cols[1:]

    logger_cols = [c for c in candidate_cols if not str(c).strip().endswith("(RH)")]
    if has_split_ts:
        # Real data: keep only the actual numeric logger-id columns, dropping
        # the metadata columns ('144\n(10 Min)', 'Hours', 'Month', 'Season').
        logger_cols = [c for c in logger_cols if _is_logger_col(c)]

    work = raw[logger_cols].copy()
    work["raw_ts"] = raw_ts
    long = work.melt(id_vars=["raw_ts"], value_vars=logger_cols,
                     var_name="logger_id", value_name="temp")
    long["logger_id"] = long["logger_id"].astype(str).str.strip()
    long["temp"] = pd.to_numeric(long["temp"], errors="coerce")
    return long.dropna(subset=["temp"]), raw_ts

def _parse_indoor_timestamps(long: pd.DataFrame, raw_ts: pd.Series, dash_is_dmy: bool) -> pd.Series:
    """Attach parsed timestamps to the melted long frame.

    The continuity check (which guards against a wrong dash convention by
    detecting backward jumps) runs on the RAW pre-melt timestamp series, which
    is the genuinely-monotonic per-row file timeline. We build a
    {raw_ts_string -> parsed timestamp} lookup from the deduplicated raw series
    and map it onto the (~1.24M) melted rows -- this both validates against the
    right (monotonic) sequence and avoids re-parsing every melted string with
    dateutil's slow per-element fallback.
    """
    unique_ts = raw_ts.drop_duplicates()
    if len(unique_ts) > 2:
        parsed_unique = dates.parse_with_continuity(
            unique_ts.reset_index(drop=True), dash_is_dmy=dash_is_dmy, expected_gap="10min"
        )
    else:
        parsed_unique = pd.to_datetime(unique_ts.reset_index(drop=True), dayfirst=dash_is_dmy)
    ts_map = dict(zip(unique_ts.tolist(), parsed_unique.tolist()))
    return long["raw_ts"].map(ts_map)

_COUNTER_COL = "144\n(10 Min)"

def _rewrite_dates_from_blocks(raw_indoor: pd.DataFrame) -> pd.DataFrame:
    """Overwrite the indoor date column with dates reconstructed from the
    144-counter block structure (for sites whose date strings are unreliable).

    The reconstructed date (ISO 'YYYY-MM-DD') replaces the raw date column;
    the existing Time column is preserved, so the downstream melt + plain
    parse produce correct timestamps without relying on a dash convention.
    """
    cols = list(raw_indoor.columns)
    time_idx = cols.index("Time")
    date_col = next(c for c in cols[: time_idx + 1]
                    if c != "Time" and c.lower() not in ("sr no", "sr no."))
    block_dates = dates.reconstruct_block_dates(
        raw_indoor[date_col], raw_indoor[_COUNTER_COL]
    )
    df = raw_indoor.copy()
    df[date_col] = block_dates.dt.strftime("%Y-%m-%d")
    return df

def run_site(adapter, site: str) -> pd.DataFrame:
    # --- Indoor ---
    raw_indoor = pd.read_csv(adapter.indoor_path(site), low_memory=False)
    raw_indoor = adapter.repair_rows(raw_indoor, kind="indoor")
    if adapter.indoor_reconstruct_dates(site):
        # Date strings are unreliable for this site (mixed convention or
        # midnight-rollover); rebuild them from the block counter so the
        # reconstructed 'YYYY-MM-DD' parses unambiguously (dash = ISO Y-M-D,
        # so dash_is_dmy is irrelevant here).
        raw_indoor = _rewrite_dates_from_blocks(raw_indoor)
        indoor_dash_is_dmy = False
    else:
        indoor_dash_is_dmy = adapter.indoor_dash_is_dmy_for(site)
    long, raw_ts = _melt_indoor(raw_indoor)
    long["timestamp"] = _parse_indoor_timestamps(long, raw_ts, indoor_dash_is_dmy)
    long, _frac = outliers.filter_indoor(long, temp_col="temp")
    nights = aggregate.to_logger_nights(long)

    # --- AWS (outdoor) ---
    raw_aws = pd.read_csv(adapter.aws_path(site), encoding=adapter.aws_encoding(site))
    raw_aws = adapter.repair_rows(raw_aws, kind="aws")
    raw_aws = raw_aws.rename(columns=adapter.column_map(site))
    date_col, time_col = raw_aws.columns[0], raw_aws.columns[1]
    combined = raw_aws[date_col].astype(str) + " " + raw_aws[time_col].astype(str)
    raw_aws["timestamp"] = pd.to_datetime(
        combined, dayfirst=adapter.aws_dash_is_dmy_for(site), errors="coerce"
    )
    raw_aws = raw_aws.dropna(subset=["timestamp"])
    raw_aws["outdoor_temp"] = pd.to_numeric(raw_aws["outdoor_temp"], errors="coerce")
    aws_nights = aggregate.to_logger_nights(
        raw_aws.assign(logger_id="_aws"), temp_col="outdoor_temp"
    ).rename(columns={"indoor_night_min": "outdoor_night_min",
                      "indoor_night_mean": "outdoor_night_mean"})[
        ["date", "outdoor_night_min", "outdoor_night_mean"]]
    nights = nights.merge(aws_nights, on="date", how="left")

    # --- Housing ---
    housing = pd.read_csv(adapter.housing_path(site), encoding=adapter.housing_encoding(site))
    hc = housing.columns
    # Prefer a column that actually names the logger ("Logger ID") over the
    # generic "Sr no"/"id" row-counter fallback -- e.g. Jalna housing has BOTH
    # "Sr no" (a row index) and "Logger ID", and matching "sr no" first would
    # join on the wrong column and drop every housing attribute.
    logger_col = next((c for c in hc if "logger" in c.lower()), None)
    if logger_col is None:
        logger_col = next(
            c for c in hc if c.lower() in ("id", "serial no", "sr no", "sr no.")
        )
    # Prefer the column that names the roof MATERIAL ("Roof structure"), not
    # secondary roof attributes like "Roof colour"/"Roof isolation"/"Roof
    # exposure"/"Roof geometry"/"Roof angle".
    roof_col = next((c for c in hc if "roof" in c.lower() and "structure" in c.lower()), None)
    if roof_col is None:
        roof_col = next((c for c in hc if c.lower() == "roof"), None)
    if roof_col is None:
        roof_col = next((c for c in hc if "roof" in c.lower()), None)
    # Prefer the explicit "is there a floor on top of this one" indicator
    # ("Floor on top" / "Floor above"), not "Floor"/"Floor number" (room
    # count) or other floor-adjacent columns.
    floor_col = next(
        (c for c in hc if "floor" in c.lower() and ("top" in c.lower() or "above" in c.lower())),
        None,
    )
    housing = housing.dropna(subset=[logger_col]).rename(columns={logger_col: "logger_id"})
    housing["logger_id"] = _normalize_logger_id(housing["logger_id"])
    housing["roof_type"] = harmonize.canonicalize_roof(housing[roof_col], adapter.roof_map(site)) if roof_col else None
    housing["floor_level"] = harmonize.canonicalize_floor(housing[floor_col], adapter.floor_map(site)) if floor_col else "other"
    housing = housing[["logger_id", "roof_type", "floor_level"]]

    df = join.attach_housing(nights, housing)
    df["site"] = site
    df = df[["site", "logger_id", "date", "indoor_night_min", "indoor_night_mean",
             "outdoor_night_min", "outdoor_night_mean", "roof_type", "floor_level"]]
    return df

def run_all(adapter=None, out_path: str | Path = "data/processed/indoor_heat_merged.parquet") -> pd.DataFrame:
    adapter = adapter or SouthAsiaAdapter()
    frames = {}
    for site in adapter.site_names:
        try:
            frames[site] = run_site(adapter, site)
        except FileNotFoundError as e:
            print(f"[skip] {site}: {e}")
    merged = merge.concat_sites(frames) if frames else pd.DataFrame()
    if not merged.empty:
        validate.check_canonical(merged)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(out_path, index=False)
        print(f"Wrote {len(merged)} logger-nights from {len(frames)} sites -> {out_path}")
    return merged

if __name__ == "__main__":
    run_all()
