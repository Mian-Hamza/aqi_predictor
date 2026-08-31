# AQI Predictor — Project Documentation

**A 100% serverless, end-to-end Air Quality Index forecasting system for Lahore, Pakistan, predicting AQI up to 3 days ahead using machine learning.**

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Final Architecture](#2-final-architecture)
3. [Phase 1: Repository & Environment Setup](#3-phase-1-repository--environment-setup)
4. [Phase 2: Feature Pipeline](#4-phase-2-feature-pipeline)
5. [Phase 3: Historical Backfill](#5-phase-3-historical-backfill)
6. [Phase 4: CI/CD Automation (GitHub Actions)](#6-phase-4-cicd-automation-github-actions)
7. [Phase 5: Training Pipeline](#7-phase-5-training-pipeline)
8. [Phase 6: Standalone Prediction Script](#8-phase-6-standalone-prediction-script)
9. [Phase 7: Streamlit Dashboard (First Web App)](#9-phase-7-streamlit-dashboard-first-web-app)
10. [Phase 8: React + FastAPI Rebuild](#10-phase-8-react--fastapi-rebuild)
11. [Phase 9: UI/UX Design Iterations](#11-phase-9-uiux-design-iterations)
12. [Phase 10: SHAP Explainability](#12-phase-10-shap-explainability)
13. [Phase 11: Deployment (Vercel + FastAPI Cloud)](#13-phase-11-deployment-vercel--fastapi-cloud)
14. [Key Lessons Learned](#14-key-lessons-learned)
15. [Final Project Structure](#15-final-project-structure)

---

## 1. Project Overview

**Goal:** Predict the Air Quality Index (AQI) for Lahore, Pakistan, up to 3 days in advance, using a fully serverless pipeline: automated data collection → feature engineering → model training → live forecasting via a web dashboard.

**Core technologies used:**
- **Python** — all pipelines and backend
- **Hopsworks** — Feature Store + Model Registry
- **Open-Meteo** — weather + air quality data (live and historical)
- **Scikit-learn / XGBoost** — Ridge, Random Forest, XGBoost models
- **SHAP** — model explainability
- **GitHub Actions** — hourly/daily pipeline automation
- **FastAPI** — backend API
- **React (Vite + Tailwind + Recharts + Framer Motion)** — frontend dashboard
- **Vercel** — frontend hosting
- **FastAPI Cloud** — backend hosting

---

## 2. Final Architecture

```
                     ┌─────────────────────┐
   Open-Meteo API →  │  feature_pipeline.py │ → Hopsworks Feature Store
   (hourly, via      │  (GitHub Actions,    │   (aqi_features)
   GitHub Actions)    │   hourly cron)       │
                     └─────────────────────┘

   Open-Meteo         ┌─────────────────────┐
   Archive API   →    │    backfill.py       │ → Hopsworks Feature Store
   (one-time)         │  (~2 years history)  │   (merged into aqi_features)
                     └─────────────────────┘

   Hopsworks           ┌─────────────────────┐
   Feature Store  →    │ training_pipeline.py │ → Hopsworks Model Registry
   (GitHub Actions,    │  3 horizons × 3 algos │   (aqi_model_day1/2/3)
    daily cron)        │  = 9 training runs    │
                     └─────────────────────┘

   Hopsworks            ┌─────────────┐        ┌──────────────────┐
   Feature Store + →    │  FastAPI     │  JSON  │   React Frontend  │
   Model Registry       │  Backend     │ ─────→ │   (Vercel)        │
                        │ (FastAPI     │        │                    │
                        │  Cloud)      │        └──────────────────┘
                        └─────────────┘
```

---

## 3. Phase 1: Repository & Environment Setup

### What was built
- Repo structure: `feature_pipeline/`, `training_pipeline/`, `backfill/`, `app/`, `notebooks/`, `.github/workflows/`
- `.env` file for secrets, `.gitignore` configured
- Hopsworks project + API key

### Errors encountered and fixes

| Error | Cause | Fix |
|---|---|---|
| `mkdir -p`, `touch` not recognized in PowerShell | PowerShell doesn't support Unix-style flags | Used `mkdir folder1, folder2` (comma-separated) and `New-Item -ItemType File` instead, or switched terminal to Git Bash |
| Confusion over where to create folder structure using Cursor | Needed repo cloned locally first | Cloned via Cursor's Git Clone command before creating any files |
| API keys pasted directly into code as `os.getenv("actual_key_value")` | Misunderstanding of how environment variables work | Corrected to `os.getenv("VARIABLE_NAME")` with real values stored only in `.env`; rotated all exposed keys |

---

## 4. Phase 2: Feature Pipeline

### What it does
Fetches current weather + pollution data, engineers time-based and lag features, computes AQI, and writes one row per run to the Hopsworks Feature Store (`aqi_features`).

### Major evolution
1. **v1**: AQICN (AQI) + OpenWeather (weather + pollutants)
2. **v2**: AQICN dropped (stale station data — confirmed via station's own `time` field never advancing); pollutants moved fully to OpenWeather's Air Pollution API
3. **v3**: Custom EPA breakpoint formula written to compute a continuous US AQI (0–500) from PM2.5/PM10, replacing OpenWeather's coarse 1–5 category
4. **v4 (final)**: Consolidated entirely onto **Open-Meteo** (weather + pollutants + `us_aqi`, precomputed server-side) for both live and historical data — ensuring the live pipeline and backfill script compute AQI identically

### Errors encountered and fixes

| Error | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'hopsworks_apigen'` | `hopsworks` package install was incomplete | Full reinstall; later understood `hopsworks_apigen` **generates** `hsml`/`hsfs`/`hopsworks_common` code locally rather than installing them as normal pip packages |
| Chain of `ModuleNotFoundError` (humps, opensearchpy, retrying, avro, build, click, fsspec, hopsworks_aiomysql, mock, pyjks, PyMySQL, tomli-w, tzlocal, cryptography) | Used `pip install hopsworks --no-deps`, which skips real dependencies | Installed each missing package manually one at a time (package name often differs from import name, e.g. `pyhumps` vs `import humps`) |
| `twofish`/`pyjks` build failure (needs Microsoft C++ Build Tools) | No C compiler on Windows | Initially worked around with `--no-deps`; ultimately required installing Visual C++ Build Tools once disk space was freed |
| `FileNotFoundError: '/tmp\\eu-west.cloud.hopsworks.ai'` | Hopsworks client hardcodes a Unix-style `/tmp` path, which Windows resolves to drive root | Manually created `C:\tmp` folder |
| `FeatureStoreException: Cannot use time_travel_format='DELTA'` | Hopsworks defaulted to Delta format, requiring an extra package | Explicitly set `time_travel_format="HUDI"` on feature group creation |
| `ModuleNotFoundError: Confluent Kafka package not found` | Insert step needs Kafka client for offline materialization | Installed `confluent-kafka` |
| `NameError: name 'jks' is not defined` | `pyjks` (needed for Kafka SSL certs) still missing | Root-caused to needing the full C++ Build Tools install — no way around it for this specific dependency |
| `FeatureStoreException: Features are not compatible with schema` (bigint vs double) | Pandas inferred `int64` for whole-number values (e.g. `aqi=34`) on first insert, locking the schema | Explicitly cast numeric columns to `float64` before every insert |
| `hour`/`day_of_week` showing wrong values | Time features computed from **UTC**, not local Lahore time | Used `ZoneInfo("Asia/Karachi")` to convert before computing time features |
| Dashboard/API showing time **5 hours ahead** | Hopsworks/Hudi types timestamp columns as UTC internally; reading back could re-attach a UTC label to what were actually local-time digits | Explicitly stripped timezone info (`tz_localize(None)`) before storing and before serving, guaranteeing naive "wall-clock" values throughout |
| `aqi`, `aqi_1h_ago` etc. always identical across runs | AQICN's station wasn't updating; later, OpenWeather's coarse 1–5 AQI scale barely moved | Switched to computing a continuous AQI from PM2.5/PM10 (EPA formula), then finally to Open-Meteo's precomputed `us_aqi` |

---

## 5. Phase 3: Historical Backfill

### What it does
Fetches ~2 years of hourly historical weather + air quality from Open-Meteo's Archive APIs, engineers the same features as the live pipeline, and bulk-inserts them into the Feature Store.

### Key design decisions
- **Separate feature group first** (`aqi_features_backfill`) used during testing to avoid corrupting live data
- Once validated, re-pointed at the live `aqi_features` group and merged in **17,544 rows**
- Lag/rolling features computed **vectorized** via `pandas.shift()` (much faster than the live pipeline's per-row "closest timestamp" lookup, since full history is available at once)

### Errors encountered and fixes

| Error | Cause | Fix |
|---|---|---|
| `Features are not compatible... (expected 'bigint', derived from input: 'int')` | `pandas.get_dummies()` and `.dt` accessors return `int32`, not `int64`, mismatching the live schema's `bigint` columns | Explicitly cast `hour`, `month`, `is_weekend` to `int64` via the underlying numpy array, with an assertion to guarantee it held |

---

## 6. Phase 4: CI/CD Automation (GitHub Actions)

### What it does
- `feature_pipeline.yml` — runs `feature_pipeline.py` every hour
- `training_pipeline.yml` — runs `training_pipeline.py` daily

### Errors encountered and fixes

| Error | Cause | Fix |
|---|---|---|
| `ValueError: invalid literal for int() with base 10: ''` | An empty `TEST_DAYS` GitHub Secret was referenced in the workflow's `env:` block, overriding the script's default with an empty string | Removed the unused secret reference entirely from the workflow YAML |
| Confusion converting cron UTC time to Lahore local time | GitHub Actions cron is always UTC | Built a reference table (Lahore time − 5 hours = UTC) for setting the correct `cron` schedule |

---

## 7. Phase 5: Training Pipeline

### Final design
- **3 independent models** (day+1, day+2, day+3), not one shared multi-output model
- **3 algorithms per horizon** (Ridge, Random Forest, XGBoost) = 9 total training runs
- Best algorithm per horizon (lowest RMSE) registered separately in the Model Registry
- Daily aggregation from hourly data, with lag/rolling/volatility features (`aqi_lag_1d/2d/3d`, `aqi_rolling_mean_14d`, `aqi_rolling_std_7d`, etc.)
- Time-based train/test split (no shuffling, since this is a time series)

### Performance investigation
Initial results showed day+1 forecasts reasonably close to target (RMSE ~27, R² ~0.57), but day+2/day+3 degraded sharply (R² dropping toward 0.1–0.2). Root cause identified: **the model has no access to future weather** — only past/current values are available as features, but weather (a real driver of AQI) 2–3 days out requires an actual forecast, not just historical patterns. Documented as a known limitation and a target for future improvement (feeding real weather forecasts as day+2/day+3 features).

### Errors encountered and fixes

| Error | Cause | Fix |
|---|---|---|
| `XGBoostError: input stream corrupted` when loading a registered model | XGBoost's own documentation warns against relying on `pickle`/`joblib` for `Booster` objects — fragile across saves/environments | Switched to XGBoost's **native** `save_model()`/`load_model()` (JSON format) for XGBoost models specifically, keeping `joblib` for Ridge/RandomForest, with a marker file (`model_type.txt`) so loaders know which format to use |

---

## 8. Phase 6: Standalone Prediction Script

A lightweight `predict.py` was built as a fast sanity check — loads the 3 registered models, builds "today's" feature row, and prints a 3-day forecast to the terminal. This logic was later reused directly inside the FastAPI backend.

---

## 9. Phase 7: Streamlit Dashboard (First Web App)

### What it showed
Current AQI (gauge), pollutants, 24-hour trend, current conditions, AI forecast (24h/48h/72h), predicted trend graph.

### Errors encountered and fixes

| Error | Cause | Fix |
|---|---|---|
| `pyarrow._flight.FlightUnavailableError` after the app sat idle | Cached Hopsworks connection went stale after inactivity | Added a TTL on the cached connection + retry-with-reconnect logic on data fetch |
| Corrupted cached model files (`FileNotFoundError` / `XGBoostError`) | Hopsworks' local download cache reused a corrupted prior download | Added automatic `clear_cache()` + retry logic when a model fails to load |
| `use_container_width` deprecation warnings | Streamlit API changing | Replaced with `width='stretch'` |

**Decision point:** Ultimately replaced with a React + FastAPI stack for a more polished, fully custom UI — Streamlit's built-in look was a limiting factor for the desired design.

---

## 10. Phase 8: React + FastAPI Rebuild

### Why this architecture
- React **cannot** safely call Hopsworks directly (would expose API keys in the browser) — needed a backend.
- **Vercel serverless functions** were considered for the backend but rejected: 10-second execution timeout on the free tier, no persistent connections — a poor fit for Hopsworks connection caching + SHAP computation.
- **FastAPI Cloud** (the official platform from the FastAPI team) chosen instead — built for persistent FastAPI apps, not short-lived functions.

### Backend (`backend/main.py`)
Reused all tested logic from the Streamlit app and `predict.py`: daily aggregation, feature building, model loading with retry logic. Exposed clean REST endpoints:
- `GET /api/health`
- `GET /api/current`
- `GET /api/trend?hours=24|48|72`
- `GET /api/forecast`
- `GET /api/explain/{horizon}`

### Frontend (`frontend/`)
Built with **Vite + React + Tailwind CSS + Recharts + Framer Motion**.

---

## 11. Phase 9: UI/UX Design Iterations

Multiple rounds of visual refinement, including:
- **AQI color scheme**: standardized on Low (blue) / Medium (green) / Above Medium (amber) / High (red), matching thresholds exactly with the backend
- **Custom AQI gauge**: SVG arc gauge, later simplified to remove a misleading tinted "trailing" background zone in favor of a neutral gray track
- **Icons**: replaced blurry/inconsistent emoji with crisp `lucide-react` SVG icons throughout
- **Custom logo**: iterated from a 4-color ring (too similar to an existing well-known brand mark) to a final gradient droplet with a pulse-line motif, symbolizing "air" + "AI-powered intelligence"
- **Sticky, translucent header**: `backdrop-blur` + semi-transparent AQI-color-tinted gradient background, later restyled into a compact single-row layout with a location pill and last-updated timestamp
- **Responsive design audit**: identified and fixed two real mobile-breakpoint gaps (header and SHAP panel headers not stacking on narrow screens)
- **Safe-vs-alert state handling**: alert banner icon/title dynamically switches between `TriangleAlert`/"Air Quality Alert" and `ShieldCheck`/"Air Quality Good" based on AQI category

### Errors encountered and fixes

| Error | Cause | Fix |
|---|---|---|
| Chart line color "overlapping" at category transitions | Multiple colored `<Area>` series each independently filled to zero, so translucent fills stacked at shared boundary points | Switched to **one single background `<Area>`** + multiple colored `<Line>` overlays (no fill) — lines can't have this overlap problem |
| Lines still diverging/crossing near a peak | Each colored `<Line>` segment's smooth (`monotone`) interpolation was computed independently, producing slightly different curve shapes near transitions | Diagnosed as needing a single continuous line with a value-based **gradient stroke** instead of multiple separate line series (final fix in progress at time of writing) |
| "Invalid Date" in chart tooltip | Tooltip was re-parsing an already-formatted display string (e.g. `"08:36 AM"`) instead of the original ISO timestamp | Read the real ISO timestamp from the original data point instead of the chart's formatted axis label |
| Y-axis values clipped (`"00"` instead of `"300"`) | Negative chart margin combined with too-narrow axis width pushed digits off-canvas | Corrected margin to a positive value and widened the Y-axis label area |

---

## 12. Phase 10: SHAP Explainability

Added a **"Why this prediction"** panel showing real SHAP feature contributions per forecast horizon.

### Implementation
- **Tree models** (Random Forest, XGBoost): `shap.TreeExplainer` — fast, exact
- **Ridge** (inside a scaling `Pipeline`): model-agnostic `shap.Explainer` built from `.predict()`, since it works regardless of internal preprocessing steps
- Friendly feature name mapping (e.g. `aqi_lag_1d` → "Current AQI", `no2` → "Nitrogen Dioxide (NO2)")
- Background/reference data sampled from historical feature rows

### Errors encountered and fixes

| Error | Cause | Fix |
|---|---|---|
| `TypeError: ufunc 'isfinite' not supported` inside SHAP | `pandas.get_dummies()` defaults to **boolean** dtype for one-hot columns, which SHAP's internal numpy operations can't handle mixed with floats | Explicitly set `dtype=int` on `get_dummies()` calls |
| Extra unnecessary Hopsworks API call per explanation request | `get_explainer()` was re-fetching the model version from Hopsworks just to build a cache key, when the caller already had it | Passed the version through directly instead of re-querying |

### Design refinements
- Colors changed from orange/green to a distinct rose/teal pair (avoiding visual confusion with the AQI category color scale used elsewhere)
- X-axis forced to whole numbers
- Tooltip restyled to white with a "Makes prediction higher/lower" explanation line

---

## 13. Phase 11: Deployment (Vercel + FastAPI Cloud)

### Frontend → Vercel
- **Root Directory** setting is critical: must be set to `frontend` (repo also contains `backend/`)
- Environment variable `VITE_API_BASE` set to the FastAPI Cloud URL

### Backend → FastAPI Cloud
- Chosen over Vercel serverless functions specifically because it supports persistent processes (better fit for Hopsworks connection caching and SHAP computation time)
- Deployed via `fastapi login` + `fastapi deploy` CLI

### Errors encountered and fixes

| Error | Cause | Fix |
|---|---|---|
| `Command "npm run build" exited with 1` — silent failure right after "transforming..." | Suspected initially to be the common Rollup native-binary/npm bug (Windows-generated lock file vs Linux build environment) | Ruled out once the real error surfaced |
| `Could not resolve "./lib/api.js"` | `.gitignore` had a bare `lib/` rule (from a generic Python template) that was **also** silently excluding the frontend's `src/lib/` folder — the file was never actually committed | Anchored the rule to `/lib/` (repo-root only) so it stopped matching `frontend/src/lib/` |
| `Could not resolve "./components/TrendChart.jsx"` | File was tracked in git as `Trendchart.jsx` (wrong case) — worked fine on case-insensitive Windows, broke on case-sensitive Linux build | Used a two-step `git mv` (rename to temp name, then to correct name) to force git to register the case change; same issue found and fixed for `WhyPrediction.jsx` |
| `RuntimeError: To use the fastapi command, please install "fastapi[standard]"` | `requirements.txt` had plain `fastapi` + separate `uvicorn[standard]`, but FastAPI Cloud's runtime specifically needs the `[standard]` extra | Changed to `fastapi[standard]` in `requirements.txt` |
| `ImportError: cannot import name 'connected' from 'hsml.decorators'` (locally **and** in the cloud) | `hopsworks` 5.0.4 (via its `hopsworks-apigen` code-generation mechanism) produced an incompatible `hsml` module; confirmed reproducible even after deleting and reinstalling the exact same version | Pinned `hopsworks==4.8.4` (last known-stable release) instead of the newest `5.0.4` |
| `Environment variable value must not be empty` (FastAPI Cloud UI) | `FRONTEND_ORIGIN` field left blank while setting up secrets | Filled with a temporary placeholder, updated to the real Vercel URL once available |
| `Failed to fetch` + browser CORS error, but root cause was a `500` | Backend crashing with an unhandled exception; the resulting broken response lacked proper CORS headers, which browsers report as a CORS block even though the true cause is different | Diagnosed by checking FastAPI Cloud's runtime logs directly rather than trusting the browser's CORS message |
| `TypeError: Metaclasses with custom tp_new are not supported` deep inside `google.protobuf` | FastAPI Cloud's default runtime used **Python 3.14**, and the compiled `protobuf` C-extension (`google._upb._message`, pulled in via Hopsworks' gRPC/istio client) isn't yet compatible with Python 3.14's changes to metaclass handling | Added a `pyproject.toml` with `requires-python = ">=3.11,<3.14"` to force FastAPI Cloud onto a compatible older Python version |

---

## 14. Key Lessons Learned

1. **Windows vs. Linux differences bite repeatedly.** Case-sensitive filenames, path separators, and even `mkdir`/`touch` syntax differences between PowerShell and Bash caused multiple real bugs that only surfaced once deploying to Linux-based cloud platforms.
2. **Pin your dependency versions, especially for actively-developed packages.** The `hopsworks` package's newest release (5.0.4) introduced a real regression; pinning to the previous stable release (4.8.4) was the correct fix, not chasing the "latest."
3. **Timezone handling needs a deliberate, consistent strategy.** Silently mixing naive and timezone-aware timestamps caused a recurring "N hours off" bug across multiple layers (database, backend, frontend) until a single clear convention (store everything as naive local time) was adopted everywhere.
4. **Schema consistency matters enormously for feature stores.** Small, easy-to-miss type differences (int32 vs int64, bool vs int) repeatedly broke inserts into Hopsworks — worth validating dtypes explicitly rather than trusting pandas' automatic inference.
5. **Don't assume a general-purpose serialization method works for every model type.** XGBoost's own documentation recommendation (native format over pickle) turned out to be correct and necessary, not just a suggestion.
6. **Match your hosting platform to your workload.** A short-timeout serverless platform (Vercel functions) is a poor fit for a backend doing real ML inference and SHAP computation — a platform designed for persistent processes (FastAPI Cloud) was the right choice.
7. **When debugging, always get the real underlying error, not the surface symptom.** Several issues (the CORS error masking a 500, the "Failed to fetch" masking a wrong API URL) required going one layer deeper — checking actual server logs or browser dev tools Network tab — before the true cause was visible.

---

## 15. Final Project Structure

```
aqi_predictor/
├── .github/
│   └── workflows/
│       ├── feature_pipeline.yml
│       └── training_pipeline.yml
├── feature_pipeline/
│   └── feature_pipeline.py
├── backfill/
│   └── backfill.py
├── training_pipeline/
│   └── training_pipeline.py
├── predict.py
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── index.css
│       ├── lib/
│       │   ├── api.js
│       │   └── aqiColor.js
│       └── components/
│           ├── AqiGauge.jsx
│           ├── Common.jsx
│           ├── Header.jsx
│           ├── CurrentAqiPanel.jsx
│           ├── TrendChart.jsx
│           ├── Forecast.jsx
│           └── WhyPrediction.jsx
├── .env
├── .gitignore
└── README.md
```

**Deployed at:**
- Frontend: Vercel
- Backend: FastAPI Cloud


