# Design: Modular Indoor-Heat Dataset Pipeline + `prana/` Engine Package

**Date:** 2026-06-26
**Status:** Approved (pending written-spec review)
**Scope:** Two ordered parts — (A) package the formula engine into `prana/`, then (B) build a plugin-style pipeline that cleans, harmonizes, and merges the South Asia indoor-heat dataset (all 5 sites) into one dataset, plus a cross-site mixed-effects regression.

---

## 1. Goals & Non-Goals

### Goals
- Make the codebase modular: a clean importable engine package (`prana/`) and a separate, non-shipping `research/` analysis layer.
- Re-process **all 5 South Asia sites** (Delhi, Dhaka, Faisalabad, Jalna, Yavatmal) from the raw Figshare zip into a single merged, analysis-ready dataset (one row per logger-night).
- Build the pipeline plugin-style so adding an external dataset later (e.g. Ghana, *if* it becomes publicly available) is "write one new adapter," not a rewrite.
- Run a cross-site mixed-effects regression validating/calibrating the indoor-temperature offsets PRANA's RDS uses.

### Non-Goals (explicit YAGNI for this work)
- Layer-2 per-household adaptive personalization (empirical-Bayes shrinkage) — separate follow-up.
- Wiring regression results back into `config.py` RDS offset constants — separate follow-up.
- WhatsApp / LLM / scheduler work.
- Any non-public dataset. Ghana (Wilby et al. 2021) is "available on request," not openly downloadable, so it is **out of scope**; the adapter design simply leaves room for it.

---

## 2. Directory Layout

```
prana-repo/
├── prana/                      # Layer 1: engine package (moved from repo root)
│   ├── __init__.py
│   ├── config.py
│   ├── ccri_calculator.py   ha_aqi_calculator.py   ndt_calculator.py
│   ├── rds_calculator.py    data_fetcher.py        uhi_lookup.py
│   ├── location_detector.py  prana_system.py
├── backend/                    # FastAPI app — imports `from prana...`
├── research/                   # Layer 2: NON-shipping analysis (tracked in git)
│   └── indoor_heat/
│       ├── __init__.py
│       ├── core/               # source-agnostic pipeline steps (pure functions)
│       │   ├── __init__.py
│       │   ├── load.py  repair.py  dates.py  outliers.py
│       │   ├── aggregate.py  harmonize.py  join.py  validate.py  merge.py
│       ├── adapters/           # one adapter per data source
│       │   ├── __init__.py
│       │   ├── base.py         # SourceAdapter Protocol
│       │   └── south_asia/     # the only adapter built in this work
│       │       ├── __init__.py
│       │       └── adapter.py
│       ├── run_pipeline.py     # CLI: runs adapter(s) → merged dataset
│       ├── regression.py       # mixed-effects model on merged data
│       └── fetch_data.py       # downloads Figshare zip → data/raw/ (fallback)
├── data/                       # gitignored; auto-created
│   ├── raw/                    # unzipped Figshare CSVs (placed manually or via fetch_data)
│   ├── interim/                # per-site cleaned parquet
│   └── processed/              # final merged dataset (single parquet)
├── tests/                      # imports `from prana...`; gains conftest/pyproject resolution
│   └── research/               # new tests for pipeline core + adapters
├── pyproject.toml              # new: makes `prana` installable; kills sys.path hacks
└── docs/superpowers/specs/
```

**Dependency rule:** `research/` imports `prana`, never the reverse. The deployable backend never ships `research/` or `data/` — enforced via `.dockerignore`.

---

## 3. Part A — Engine Package Refactor (done first, atomic)

1. Create `prana/__init__.py`; `git mv` the 9 root modules into `prana/`.
2. Rewrite imports (~20 sites):
   - Inside the 9 modules: `from config import *` → `from prana.config import *`; `from data_fetcher import ...` → `from prana.data_fetcher import ...` (note: `prana_system.py` imports 6 siblings).
   - `backend/main.py`, `backend/llm.py`: `from prana_system import ...` → `from prana.prana_system import ...`, etc.
   - `scripts/ccri_rds_sensitivity.py`: bare imports → `prana.` imports.
   - All 9 files in `tests/`: `from ccri_calculator import ...` → `from prana.ccri_calculator import ...`.
3. Add `pyproject.toml` declaring the `prana` package so `pip install -e .` makes imports resolve everywhere.
4. Remove now-unnecessary `sys.path` hacks in `backend/main.py` (lines ~24-25) and `scripts/ccri_rds_sensitivity.py` (line ~19).
5. Add test import resolution (`conftest.py` at repo root or `[tool.pytest.ini_options]` in `pyproject.toml`) so tests no longer depend on being run from a specific cwd.
6. Re-check `Dockerfile` / `.dockerignore` / `scripts/deploy.sh` so the package still ships correctly and `data/`+`research/` are excluded.

**Verification gate:** the full existing test suite must pass after the move before this commit is finalized. No behavior change is intended — only import paths.

**Commit boundary:** Part A (engine refactor) is committed separately from Part B (pipeline), so the import-path change is reviewable and bisectable in isolation. Part B builds on the committed package state.

---

## 4. Part B — Plugin Pipeline

### 4.1 Adapter interface (`adapters/base.py`)

Each data source implements a `SourceAdapter`:

```python
class SourceAdapter(Protocol):
    name: str                                  # "south_asia"
    site_names: list[str]                      # ["delhi","dhaka","faisalabad","jalna","yavatmal"]
    def indoor_path(self, site: str) -> Path
    def aws_path(self, site: str) -> Path
    def housing_path(self, site: str) -> Path
    def parse_indoor_dates(self, raw) -> "datetime series"   # indoor dash-format = DD-MM-YYYY
    def parse_aws_dates(self, raw) -> "datetime series"      # AWS dash-format = MM-DD-YYYY (opposite!)
    def repair_rows(self, raw, kind: str) -> "df"            # Dhaka AWS "2016"-split fix; default no-op
    def roof_map(self, site: str) -> dict                    # raw roof label → {tin,concrete,brick,stone}
    def floor_map(self, site: str) -> dict                   # "Floor on top"/"Floor above" → {top,other}
    def column_map(self, site: str) -> dict                  # "Temp Out"/"Air temperature" → canonical
```

The South Asia adapter encodes all known per-site quirks: the **opposite dash-format conventions between indoor (DD-MM) and AWS (MM-DD) files**, the **Dhaka AWS "2016"-split row corruption** (regex `^(\d)\s+(\d{1,2}:\d{2}.*)$` on the raw unstripped Time string, with the special-cased legitimate-midnight fallback), and per-site non-standardized housing column names. Rural sites (Jalna, Yavatmal) use generic "Air temperature" AWS columns vs urban "Temp Out".

### 4.2 Core pipeline steps (source-agnostic, pure functions)

Run identically for every adapter, each step a pure `df -> df`:

1. **load** — read raw CSV via adapter paths.
2. **repair** — call `adapter.repair_rows` (Dhaka AWS; no-op elsewhere).
3. **parse_dates** — apply adapter date rules, then a **continuity check**: assert no negative time jumps and expected gap cadence (10-min indoor, 1-hour AWS). Hard-fail loudly on violation — this is the automated guard against the date-format bug class hit during manual analysis. Never trust the column header's stated format; verify by continuity.
4. **filter_outliers** — drop indoor readings outside 15–50°C (config constant); log % removed (~0.2% expected for Delhi).
5. **aggregate** — collapse to **one row per (logger, night)**: indoor night-min and night-mean over 22:00–06:00, joined to that night's outdoor min/mean. This is the unit RDS operates on and the unit that avoids pseudo-replication.
6. **harmonize** — apply adapter roof/floor/column maps → canonical schema.
7. **join** — attach housing characteristics per logger_id. Exclude logger IDs suffixed `(RH)` (humidity, not temperature).
8. **validate** — assert canonical schema, non-null join keys, plausible ranges.
9. **merge** — concatenate all sites into one dataset, adding a `site` column (the mixed-model grouping factor).

### 4.3 Canonical merged schema (one row = one logger-night)

```
site, logger_id, date,
indoor_night_min, indoor_night_mean,
outdoor_night_min, outdoor_night_mean,
roof_type   ∈ {tin, concrete, brick, stone},
floor_level ∈ {top, other},
<other harmonized housing chars present per-site, sparse where not universal>
```

Housing characteristics not present across all 5 sites remain as **sparse columns** — kept in the merged data, but the regression only consumes universally-present predictors (outdoor temp, roof_type, floor_level).

### 4.4 Output

`data/processed/indoor_heat_merged.parquet` — the single merged dataset. Per-site interim parquet under `data/interim/` for debugging/inspection.

---

## 5. Regression (`research/indoor_heat/regression.py`)

- **Model:** `indoor_night_min ~ outdoor_night_min * roof_type + floor_level` with **site as a grouping factor** — `statsmodels` MixedLM, random intercept + random `outdoor_night_min` slope per site. The random effect is what allows safe cross-site (and future cross-dataset) combination.
- **Outputs:** per-roof-type slope vs outdoor temperature (the tin-roof nonlinearity), coefficients with confidence intervals, R², RMSE — same outputs validated for Delhi (R²≈0.157, RMSE≈1.96°C for Delhi alone; the merged multi-site numbers will differ).
- **Pseudo-replication guard:** merged data is one-row-per-logger-night by construction, so the analysis unit is correct. An optional `--raw-check` flag runs the naive per-reading regression alongside to demonstrate the SE/p-value inflation; not the default.
- **Dependencies:** `statsmodels` (and `pyarrow` for parquet) go in a **research-only** dependency group in `pyproject.toml`, NOT in the backend `requirements.txt`, keeping the deployable image lean.

---

## 6. Data Acquisition (`research/indoor_heat/fetch_data.py`)

Downloads the Figshare zip (DOI 10.6084/m9.figshare.12546368, ~54MB) to `data/raw/` and unzips. Since the user is placing the zip manually, this is a reproducibility/fallback tool; the pipeline reads from `data/raw/` regardless of how the files got there.

---

## 7. Testing Strategy

- **Engine (Part A):** existing test suite must stay green through the refactor — import-path-only change, no behavior change.
- **Pipeline core:** unit test each pure function with synthetic edge cases:
  - date-continuity check, including the Dhaka midnight false-positive (looks corrupted, isn't),
  - outlier-filter boundaries (15°C / 50°C edges),
  - night-aggregation windowing (22:00–06:00 boundary handling, cross-midnight night-keying),
  - harmonization maps (roof/floor canonicalization).
- **Adapters:** per-site smoke test asserting cleaned output has zero negative date jumps and expected gap cadence — the automated form of the manual continuity-checking done previously.

---

## 8. Known Data-Quality Facts Encoded (from prior analysis)

- Date formats mix DD-MM and MM-DD **within single files** at month-boundary transitions. Indoor files: dash = DD-MM-YYYY. AWS files: dash = MM-DD-YYYY (**opposite**). Confirmed on Delhi and Dhaka; assumed consistent per file-type across sites but **verified by continuity check at runtime**, not assumed.
- Dhaka AWS: ~44% of rows have "2016" split across date/time columns — requires regex repair with a special-cased legitimate-midnight fallback. Not yet confirmed needed for Faisalabad/Jalna/Yavatmal — the adapter applies the repair and the continuity check will reveal if it's required/sufficient elsewhere.
- Indoor outlier spikes (60–79°C at 2–4 AM) from disturbed loggers → 15–50°C filter.
- The dataset has **zero AC variation** (urban households selected for AC absence) — an AC coefficient cannot be fit from this data; that offset stays literature-based and is out of scope here.

---

## 9. Risks

- **Engine refactor blast radius:** ~20 import sites across backend/tests/scripts; tests currently have no import-resolution config. Mitigated by the atomic-commit + full-suite-green gate.
- **Per-site date/corruption surprises:** Faisalabad/Jalna/Yavatmal may have quirks not seen in Delhi/Dhaka. Mitigated by the hard-failing continuity check — the pipeline refuses to emit silently-wrong dates.
- **Sparse housing columns** across sites may limit which predictors are universally usable; regression restricts to the common set by design.
