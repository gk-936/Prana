import pandas as pd

_REQUIRED = ["site","logger_id","date","indoor_night_min","indoor_night_mean",
             "outdoor_night_min","outdoor_night_mean","roof_type","floor_level"]
_ROOF_OK = {"tin","concrete","brick","stone", None}
_FLOOR_OK = {"top","other", None}

def check_canonical(df: pd.DataFrame) -> None:
    for col in _REQUIRED:
        assert col in df.columns, f"missing required column: {col}"
    assert df["logger_id"].notna().all(), "null logger_id present"
    bad_roof = set(df["roof_type"].dropna().unique()) - _ROOF_OK
    assert not bad_roof, f"non-canonical roof_type values: {bad_roof}"
    bad_floor = set(df["floor_level"].dropna().unique()) - _FLOOR_OK
    assert not bad_floor, f"non-canonical floor_level values: {bad_floor}"
