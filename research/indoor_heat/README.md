# Indoor-Heat Dataset Pipeline

A modular, plugin-style pipeline that cleans and merges the South Asia
indoor-heat dataset into a single analysis-ready table (one row per
logger-night), then fits a cross-site mixed-effects regression of indoor
night temperature on outdoor temperature, roof type, and floor level.

It exists to calibrate PRANA's RDS indoor-temperature offsets (the
`RDS_ONBOARDING_*` constants) against real measurements instead of
prototype assumptions.

## Layout

```
research/indoor_heat/
├── fetch_data.py        # download/extract the Figshare zip into data/raw/
├── adapters/
│   ├── base.py          # SourceAdapter protocol (the plugin interface)
│   └── south_asia/      # the South Asia adapter (per-site quirks live here)
├── core/                # source-agnostic steps (pure DataFrame -> DataFrame)
│   ├── outliers.py  aggregate.py  dates.py
│   ├── harmonize.py join.py  validate.py  merge.py
├── run_pipeline.py      # wires adapter + core -> merged parquet
└── regression.py        # cross-site mixed-effects model
```

Adding a new dataset later = write one new adapter under `adapters/`; the
`core/` steps and `run_pipeline.py` stay unchanged.

## Data

Dataset: *Indoor Heat Measurement Data from Low-income Households in Rural and
Urban South Asia* — Figshare DOI `10.6084/m9.figshare.12546368`
(paper: Nature Scientific Data `10.1038/s41597-022-01314-5`).

Raw data is **not** committed (it lives under the git-ignored `data/`). To get it:

```bash
# Option A: automated
python -m research.indoor_heat.fetch_data        # -> data/raw/

# Option B: manual
# unzip 12546368.zip into data/raw/ so it contains
#   "Delhi Indoor Data.csv", "Delhi AWS Data.csv", "Delhi Housing Structure Data.csv", ...
```

## Running

```bash
# Clean + merge all sites -> data/processed/indoor_heat_merged.parquet
python -m research.indoor_heat.run_pipeline

# Fit the cross-site regression on the merged parquet
python -m research.indoor_heat.regression
# add --raw-check to also print the naive (pseudo-replicated) OLS for comparison
```

Both require the research extras: `pip install -e .[research]`.

## Canonical merged schema (one row = one logger-night)

| column | meaning |
|---|---|
| `site` | delhi / dhaka / faisalabad / jalna / yavatmal (the mixed-model grouping factor) |
| `logger_id` | indoor logger id |
| `date` | the night's date (night window 22:00–06:00; early-morning hours key to the previous day) |
| `indoor_night_min`, `indoor_night_mean` | indoor temp over the night |
| `outdoor_night_min`, `outdoor_night_mean` | nearest AWS station's outdoor temp that night |
| `roof_type` | canonical {tin, concrete, brick, stone}; unmapped/other → null |
| `floor_level` | {top, other} where a "floor on top" indicator exists; else other |

Housing attributes that don't exist across all sites are dropped; the
regression uses only the universally-present predictors.

## Results (all 5 sites)

Merged dataset: **43,418 logger-nights** across 5 sites.

| site | logger-nights | loggers | outdoor coverage |
|---|---|---|---|
| delhi | 8,672 | 57 | 92% |
| dhaka | 10,599 | 59 | 76% |
| faisalabad | 7,875 | 48 | 54% |
| jalna | 4,080 | 16 | 72% |
| yavatmal | 12,192 | 20 | 61% |

Mixed-effects model
`indoor_night_min ~ outdoor_night_min * C(roof_type) + C(floor_level)`,
grouped by `site` (random intercept + random outdoor slope), on the
**26,501** logger-nights with non-null outdoor temp + roof type:

- **R² (marginal) = 0.564, RMSE = 2.48 °C**
- Roof baseline offsets (vs. brick reference): tin **+1.95 °C**, concrete
  **+1.40 °C**, stone **+0.56 °C**.
- `outdoor_night_min` main slope **+0.343**; roof × outdoor interactions:
  tin **−0.054**, concrete **−0.021**, stone **+0.039**.

Interpretation: pooled across 5 climates, tin roofs run hottest at the
baseline (cool nights) but their *interaction* slope is negative, i.e. the
tin-vs-brick gap narrows as outdoor temperature rises. This is a more nuanced
picture than a single-site (Delhi-only) fit, because the site random effect
absorbs between-climate variation. These coefficients are descriptive for
this sample and are **not yet** wired into PRANA's RDS constants — that
calibration is a separate, deliberate follow-up.

## Per-site data-quality quirks handled

The dataset's date columns are notoriously inconsistent; the pipeline's
`dates.parse_with_continuity` guard hard-fails on backward time jumps so a
wrong convention can never silently corrupt the output. Discovered, by
running against the guard (not by trusting the file headers, which all say
"DD/MM/YYYY"):

- **Indoor dash-date convention varies by site.** Dhaka/Faisalabad are
  day-first (DD-MM); Delhi and Jalna are month-first (MM-DD) — contradicting
  the prior assumption that all indoor files were day-first.
- **AWS dash-date convention is mostly month-first (MM-DD)** for urban sites,
  but the rural AWS files (Jalna, Yavatmal) are day-first (DD-MM).
- **Faisalabad indoor dates FLIP convention mid-file** (a block stamped
  `28-03` DD-MM, the next stamped `03-28` MM-DD) and **Yavatmal indoor dates
  repeat across midnight** (a block fails to advance the date). Neither can be
  parsed with a single convention flag, so both are reconstructed from the
  `144\n(10 Min)` intra-day counter via `dates.reconstruct_block_dates`: the
  counter's 1..144 cycle gives a trustworthy block structure even when the
  date strings don't, and each block is re-dated as anchor + N days. Short
  blocks (a day with fewer than 144 readings) are detected by a counter
  *drop*, not by "previous == 144".
- **Dhaka AWS has a "2016"-year split** (the year's last digit lands on the
  Time column); repaired in the adapter's `repair_rows`.
- **Jalna housing has both "Sr no" and "Logger ID"** — the join must prefer
  the "logger" column or it silently drops every housing attribute.
- **Some rural files are latin-1 encoded** (per-site encoding overrides in the
  adapter).
- **Indoor outlier spikes** (loggers physically disturbed) are filtered to a
  plausible 15–50 °C band.

## Known limitations

- The dataset has **zero AC variation** (urban households were selected for
  AC *absence*), so an AC offset cannot be fit here — it stays literature-based.
- Outdoor coverage varies by site (54–92%); logger-nights without a matching
  AWS night are kept in the merged file but excluded from the regression.
- Aggregation is to logger-nights specifically to avoid the pseudo-replication
  that inflates significance when raw 10-minute readings are treated as
  independent.
