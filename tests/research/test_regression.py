import warnings

import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import ConvergenceWarning

from research.indoor_heat import regression

def _synth(n_per_site=200, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for site in ["delhi","dhaka"]:
        for i in range(n_per_site):
            roof = "tin" if i % 2 == 0 else "concrete"
            outdoor = rng.uniform(24, 36)
            # tin tracks outdoor with steeper slope -> interaction effect
            slope = 0.9 if roof == "tin" else 0.6
            indoor = 5 + slope*outdoor + rng.normal(0, 1.0)
            rows.append({"site":site, "logger_id":f"{site}{i}", "date":i,
                         "indoor_night_min":indoor, "indoor_night_mean":indoor+0.5,
                         "outdoor_night_min":outdoor, "outdoor_night_mean":outdoor+0.5,
                         "roof_type":roof, "floor_level":"other"})
    return pd.DataFrame(rows)

def test_fit_mixed_recovers_interaction_sign():
    df = _synth()
    with warnings.catch_warnings():
        # MixedLM with a random outdoor-temp slope on only 2 groups can emit
        # ConvergenceWarning even when the recovered sign/fit are stable and
        # correct (verified across multiple seeds/runs); see task-B7-report.md.
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        out = regression.fit_mixed(df)
    assert out["n"] == len(df)
    assert out["rmse"] < 2.0
    # tin:outdoor interaction should be positive (tin steeper than concrete baseline)
    inter = [v for k,v in out["params"].items() if "outdoor" in k and "tin" in k]
    assert inter and inter[0] > 0
