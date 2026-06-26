import pandas as pd

def canonicalize_roof(series: pd.Series, roof_map: dict) -> pd.Series:
    norm = series.astype(str).str.strip().str.lower()
    out = norm.map(roof_map)  # unmapped -> NaN/None
    return out.where(out.notna(), None)

def canonicalize_floor(series: pd.Series, floor_map: dict) -> pd.Series:
    norm = series.astype(str).str.strip().str.lower()
    return norm.map(lambda v: floor_map.get(v, "other"))
