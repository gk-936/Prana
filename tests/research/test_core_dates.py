import pandas as pd
import pytest
from research.indoor_heat.core.dates import parse_with_continuity, DateContinuityError

def test_indoor_dash_is_ddmmyyyy():
    # 20-03-2016 must parse as 20 March (DD-MM), proving DMY for indoor
    s = pd.Series(["20-03-2016 00:00", "20-03-2016 00:10"])
    out = parse_with_continuity(s, dash_is_dmy=True, expected_gap="10min")
    assert out.iloc[0].month == 3 and out.iloc[0].day == 20

def test_aws_dash_is_mmddyyyy():
    # 04-12-2016 then 4/12/2016 02:00 only continuous (1h gap) if dash = MM-DD (April 12)
    s = pd.Series(["04-12-2016 01:00", "4/12/2016 02:00"])
    out = parse_with_continuity(s, dash_is_dmy=False, expected_gap="1h")
    assert out.iloc[0].month == 4 and out.iloc[0].day == 12
    assert out.iloc[1].hour == 2

def test_negative_jump_raises():
    s = pd.Series(["20-03-2016 00:10", "20-03-2016 00:00"])  # goes backwards
    with pytest.raises(DateContinuityError):
        parse_with_continuity(s, dash_is_dmy=True, expected_gap="10min")
