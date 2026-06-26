"""Cross-site mixed-effects regression of indoor night temp on outdoor temp,
roof type (with interaction), and floor level. Site is the grouping factor."""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

FORMULA = "indoor_night_min ~ outdoor_night_min * C(roof_type) + C(floor_level)"


def fit_mixed(df: pd.DataFrame) -> dict:
    d = df.dropna(subset=["indoor_night_min", "outdoor_night_min", "roof_type"]).copy()
    model = smf.mixedlm(FORMULA, d, groups=d["site"],
                         re_formula="~outdoor_night_min")
    res = model.fit(method="lbfgs", maxiter=200, disp=False)
    pred = res.fittedvalues
    resid = d["indoor_night_min"].values - pred.values
    rmse = float(np.sqrt(np.mean(resid**2)))
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((d["indoor_night_min"] - d["indoor_night_min"].mean())**2))
    r2 = 1 - ss_res/ss_tot if ss_tot else float("nan")
    return {"params": dict(res.fe_params), "r2_marginal": r2, "rmse": rmse, "n": len(d)}


def main(parquet_path: str = "data/processed/indoor_heat_merged.parquet", raw_check: bool = False):
    df = pd.read_parquet(parquet_path)
    out = fit_mixed(df)
    print(f"n={out['n']}  R2(marginal)={out['r2_marginal']:.3f}  RMSE={out['rmse']:.2f}degC")
    print("Fixed effects:")
    for k, v in out["params"].items():
        print(f"  {k:45s} {v:+.4f}")
    if raw_check:
        import statsmodels.formula.api as smf2
        raw = smf2.ols(FORMULA, df.dropna(subset=['indoor_night_min', 'outdoor_night_min', 'roof_type'])).fit()
        print("\n[raw-check] naive OLS (pseudo-replicated if run on per-reading data):")
        print(f"  R2={raw.rsquared:.3f}  (compare SE/p-values with caution)")


if __name__ == "__main__":
    import sys
    main(raw_check="--raw-check" in sys.argv)
