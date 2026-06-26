"""Download and extract the South Asia indoor-heat dataset (Figshare 12546368)."""
import zipfile
from pathlib import Path
import urllib.request

RAW_DIR = Path("data/raw")
FIGSHARE_ZIP_URL = "https://figshare.com/ndownloader/articles/12546368/versions/1"

def extract_zip(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    return dest

def download_and_extract(dest: Path = RAW_DIR) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "12546368.zip"
    if not zip_path.exists():
        urllib.request.urlretrieve(FIGSHARE_ZIP_URL, zip_path)
    return extract_zip(zip_path, dest)

if __name__ == "__main__":
    out = download_and_extract()
    print(f"Extracted to {out}")
