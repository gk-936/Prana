import pandas as pd

def concat_sites(frames: dict) -> pd.DataFrame:
    out = []
    for site, df in frames.items():
        d = df.copy()
        d["site"] = site
        out.append(d)
    return pd.concat(out, ignore_index=True)
