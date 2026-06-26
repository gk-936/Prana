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

def parse_with_continuity(series: pd.Series, dash_is_dmy: bool, expected_gap: str) -> pd.Series:
    parsed = series.map(lambda v: _parse_one(v, dash_is_dmy))
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
