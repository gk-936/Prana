from research.indoor_heat.adapters.south_asia.adapter import SouthAsiaAdapter

def test_site_names():
    a = SouthAsiaAdapter(raw_dir="data/raw")
    assert set(a.site_names) == {"delhi","dhaka","faisalabad","jalna","yavatmal"}

def test_dash_conventions_opposite():
    a = SouthAsiaAdapter(raw_dir="data/raw")
    assert a.indoor_dash_is_dmy is True
    assert a.aws_dash_is_dmy is False

def test_roof_map_canonicalizes_tin():
    a = SouthAsiaAdapter(raw_dir="data/raw")
    m = a.roof_map("delhi")
    # raw label (lowercased) maps to canonical
    assert m.get("tin") == "tin" or "tin" in m.values()
