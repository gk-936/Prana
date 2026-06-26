from pathlib import Path
from research.indoor_heat import fetch_data

def test_raw_dir_constant():
    assert fetch_data.RAW_DIR == Path("data/raw")

def test_extract_existing_zip(tmp_path):
    # Build a tiny fake zip and confirm extraction lands files in dest
    import zipfile
    z = tmp_path / "sample.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("Delhi Indoor Data.csv", "Timestamp,L1\n01-03-2016 00:00,30.0\n")
    dest = tmp_path / "raw"
    out = fetch_data.extract_zip(z, dest)
    assert (out / "Delhi Indoor Data.csv").exists()
