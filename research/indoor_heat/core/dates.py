import pandas as pd

class DateContinuityError(ValueError):
    """Raised when parsed dates jump backwards or gaps don't match expectation."""

_GAP = {"10min": pd.Timedelta(minutes=10), "1h": pd.Timedelta(hours=1)}

def _parse_one(value: str, dash_is_dmy: bool):
    v = str(value).strip()
    if "-" in v.split(" ")[0]:
        dayfirst = dash_is_dmy
    else:
        dayfirst = False  # slash blocks are M/D/Y in this dataset
    return pd.to_datetime(v, dayfirst=dayfirst, errors="coerce")

def _parse_vectorized(series: pd.Series, dash_is_dmy: bool) -> pd.Series:
    """Vectorized equivalent of series.map(_parse_one, ...).

    Real-data series can be tens of thousands of rows; per-row dateutil
    fallback (via .map) is too slow at that scale. Split into the two
    known sub-formats (dash-leading-block vs slash-leading-block) and
    parse each homogeneous subset in one vectorized pd.to_datetime call.
    """
    s = series.astype(str).str.strip()
    first_block = s.str.split(" ", n=1).str[0]
    is_dash = first_block.str.contains("-")
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    if is_dash.any():
        out.loc[is_dash] = pd.to_datetime(s[is_dash], dayfirst=dash_is_dmy, errors="coerce")
    if (~is_dash).any():
        out.loc[~is_dash] = pd.to_datetime(s[~is_dash], dayfirst=False, errors="coerce")
    return out

def reconstruct_block_dates(date_str: pd.Series, counter: pd.Series) -> pd.Series:
    """Reconstruct per-row dates from a daily block counter, robust to mixed
    DD-MM/MM-DD conventions and midnight-rollover corruption.

    Some indoor files cannot be parsed with a single dash_is_dmy flag:
    - Faisalabad FLIPS convention mid-file (a block stamped '28-03' DD-MM,
      the next stamped '03-28' MM-DD).
    - Yavatmal repeats the previous day's date for whole blocks (the date
      string fails to advance at midnight).

    The '144\\n(10 Min)' counter is a reliable 1..144 intra-day cycle, so the
    block STRUCTURE (which rows form one logical day) is trustworthy even when
    the date STRINGS are not. Strategy: split into blocks (one per 144-row
    day), establish each block's calendar date by majority-vote of a
    day-ambiguity-free anchor, then assign every block date = anchor + N days
    so the output is continuous by construction. The within-block Time column
    (not handled here) carries the hour/minute.

    Args:
        date_str: raw date strings, original row order.
        counter: the 144-counter column (numeric 1..144), same index.

    Returns:
        A Series of normalized block dates (date only, time 00:00) per row.

    Raises:
        DateContinuityError if block structure can't be established.
    """
    ctr = pd.to_numeric(counter, errors="coerce")
    # A new day-block begins wherever the counter drops back toward 1. Keying
    # on "previous == 144" misses SHORT blocks (a day with fewer than 144
    # readings, e.g. a logger that stopped 6 intervals early), which would
    # otherwise merge two calendar days into one block and suppress a date
    # advance. Treating any decrease as a reset is robust to short blocks.
    is_reset = ctr < ctr.shift(1, fill_value=ctr.iloc[0] + 1)
    block_id = is_reset.cumsum()
    if block_id.nunique() < 2:
        raise DateContinuityError("Could not establish 144-row block structure")

    # For each block, parse its first row's date string BOTH ways and keep the
    # day-of-month and month components; the unambiguous component (a value
    # > 12) tells us which is day vs month. Blocks where both components are
    # <= 12 are ambiguous and resolved purely by sequence anchoring below.
    first_rows = date_str.groupby(block_id).first().astype(str).str.strip()
    # Extract the two leading numeric components and the year.
    parts = first_rows.str.replace("/", "-").str.split("-", n=2, expand=True)
    a = pd.to_numeric(parts[0], errors="coerce")
    b = pd.to_numeric(parts[1], errors="coerce")
    year = pd.to_numeric(parts[2].str.split(" ").str[0], errors="coerce")

    # Determine each block's true (month, day) where unambiguous:
    #   if a > 12 -> a is day, b is month (DD-MM)
    #   if b > 12 -> a is month, b is day (MM-DD)
    #   else ambiguous -> NaN, filled by anchoring
    month = pd.Series(pd.NA, index=first_rows.index, dtype="Float64")
    day = pd.Series(pd.NA, index=first_rows.index, dtype="Float64")
    dd_mm = a > 12
    mm_dd = b > 12
    month[dd_mm] = b[dd_mm]; day[dd_mm] = a[dd_mm]
    month[mm_dd] = a[mm_dd]; day[mm_dd] = b[mm_dd]

    anchor_date = pd.Series(pd.NaT, index=first_rows.index, dtype="datetime64[ns]")
    ok = month.notna() & day.notna() & year.notna()
    anchor_date[ok] = pd.to_datetime(
        dict(year=year[ok].astype(int), month=month[ok].astype(int), day=day[ok].astype(int)),
        errors="coerce",
    )
    if not anchor_date.notna().any():
        raise DateContinuityError("No unambiguous block date to anchor reconstruction")

    # Anchor on the first resolvable block, then assign every block a date by
    # its position offset from that anchor (block N = anchor + (N - anchor_pos)
    # days). Block order is the cumsum order, i.e. file order.
    block_index = pd.Series(range(len(first_rows)), index=first_rows.index)
    first_ok_pos = block_index[anchor_date.notna()].iloc[0]
    first_ok_date = anchor_date[anchor_date.notna()].iloc[0]
    block_dates = first_ok_date + pd.to_timedelta(block_index - first_ok_pos, unit="D")

    # Map block date back to every row via block_id.
    block_date_by_id = pd.Series(block_dates.values, index=first_rows.index)
    return block_id.map(block_date_by_id)


def parse_with_continuity(series: pd.Series, dash_is_dmy: bool, expected_gap: str) -> pd.Series:
    parsed = _parse_vectorized(series, dash_is_dmy)
    if parsed.isna().any():
        bad = series[parsed.isna()].head(3).tolist()
        raise DateContinuityError(f"Unparseable date values, e.g. {bad}")
    diffs = parsed.diff().dropna()
    if (diffs < pd.Timedelta(0)).any():
        first_bad = parsed[1:][diffs.values < pd.Timedelta(0)].head(1).tolist()
        raise DateContinuityError(
            f"Negative time jump detected near {first_bad} "
            f"(dash_is_dmy={dash_is_dmy} likely wrong)"
        )
    median_gap = diffs.median()
    target = _GAP[expected_gap]
    # Allow generous tolerance: data has legitimate multi-step gaps; just guard order-of-magnitude.
    if median_gap > target * 3 or median_gap < target / 3:
        raise DateContinuityError(
            f"Median gap {median_gap} far from expected {target}"
        )
    return parsed
