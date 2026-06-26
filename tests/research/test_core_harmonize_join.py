import pandas as pd
import pytest
from research.indoor_heat.core import harmonize, join, validate, merge

def test_canonicalize_roof():
    s = pd.Series(["Tin", "RCC", "brick", "unknownX"])
    rm = {"tin":"tin","rcc":"concrete","brick":"brick"}
    out = harmonize.canonicalize_roof(s, rm)
    assert list(out) == ["tin","concrete","brick", None]

def test_canonicalize_floor():
    s = pd.Series(["Yes", "no", "TOP"])
    fm = {"yes":"top","top":"top"}
    out = harmonize.canonicalize_floor(s, fm)
    assert list(out) == ["top","other","top"]

def test_attach_housing():
    nights = pd.DataFrame({"logger_id":["L1","L2"], "date":["d1","d2"],
                           "indoor_night_min":[30.0,31.0]})
    housing = pd.DataFrame({"logger_id":["L1","L2"], "roof_type":["tin","concrete"],
                            "floor_level":["top","other"]})
    out = join.attach_housing(nights, housing)
    assert out.loc[out.logger_id=="L1","roof_type"].iloc[0] == "tin"

def test_merge_adds_site_column():
    f = {"delhi": pd.DataFrame({"logger_id":["L1"]}),
         "dhaka": pd.DataFrame({"logger_id":["L2"]})}
    out = merge.concat_sites(f)
    assert set(out["site"]) == {"delhi","dhaka"}

def test_validate_rejects_bad_roof():
    df = pd.DataFrame({"site":["delhi"],"logger_id":["L1"],"date":["d"],
                       "indoor_night_min":[30.0],"indoor_night_mean":[31.0],
                       "outdoor_night_min":[28.0],"outdoor_night_mean":[29.0],
                       "roof_type":["plastic"],"floor_level":["top"]})
    with pytest.raises(AssertionError):
        validate.check_canonical(df)
