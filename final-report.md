# Final Report — Pearls AQI Predictor

---

## 1) Overview

Pearls AQI Predictor is an end-to-end, serverless machine learning system that forecasts the Air Quality Index (AQI) for Lahore, Pakistan up to **three days ahead**. The system was built in distinct phases — data collection, feature engineering, model training, model registry, live serving, and a dashboard — each automated so the whole pipeline runs itself with no manual intervention once deployed.

**Final stack:**
- **Data source:** Open-Meteo (live + historical weather and air quality)
- **Feature Store & Model Registry:** Hopsworks
- **Models:** Ridge Regression, Random Forest, XGBoost
- **Automation:** GitHub Actions (hourly feature collection, daily retraining)
- **Backend:** FastAPI, deployed on FastAPI Cloud
- **Frontend:** React (Vite, Tailwind, Recharts, Framer Motion), deployed on Vercel
- **Explainability:** SHAP

**Live app:** https://aqi-predictor-green.vercel.app/

---

## 2) Data & Feature Engineering

This phase covers everything from choosing a data source to turning raw pollutant/weather readings into a model-ready dataset. It's broken down into four parts below: the exploratory look at the data, the process of settling on an API, the cleaning steps required, and the final feature set.

---

## 3) EDA & Picking the API

### EDA

Formal exploratory analysis here was mostly done *through the pipeline itself* rather than a separate notebook — inspecting live values, Hopsworks' Data Preview, and the dashboard's own trend charts as data accumulated.

**What the data showed:**
- **Lahore's AQI consistently sits in the "Above Medium" to "High" range.** Real 24-hour trend screenshots captured during development showed sustained readings in the 150–225 range, confirming Lahore's known seasonal smog problem rather than being an artifact of the pipeline.
- **AQICN's station data was frequently stale.** Cross-checking the station's own `time` field (last-measured timestamp) against the wall clock showed the "Lahore" station sometimes didn't update for hours, which explained why `aqi`, `aqi_1h_ago`, etc. looked identical across consecutive runs early on.
- **OpenWeather's own 1–5 AQI category barely moved**, even while the underlying PM2.5/PM10 concentrations clearly fluctuated — confirming a coarse categorical AQI was the wrong signal for lag/trend features, and pushing the project toward a continuous 0–500 AQI value instead.
- **PM2.5 and PM10 were the dominant drivers** of the computed AQI in nearly every case (the EPA formula takes the *max* of each pollutant's sub-index, and PM2.5/PM10 consistently produced the highest sub-index in Lahore's data) — later confirmed quantitatively by SHAP, which almost always ranked "Current AQI" (itself downstream of PM2.5/PM10) and PM2.5 among the top contributors to every forecast.

### Picking the API

The data source went through several iterations before settling on a final choice:

1. **AQICN (AQI) + OpenWeather (weather + pollutants).** Initial combination. Abandoned once AQICN's station was confirmed stale via its own timestamp field.
2. **OpenWeather only**, using its Air Pollution API for pollutants and a hand-written US EPA breakpoint formula to compute a continuous AQI from PM2.5/PM10. This fixed the "AQI never changes" problem, but meant maintaining a duplicate EPA formula in two separate scripts (live pipeline and backfill), risking drift between them.
3. **Open-Meteo (final choice)** — for weather, pollutants, *and* a precomputed `us_aqi` value, from a **single provider**, with **both a live/current endpoint and a historical archive endpoint using the same data model**. This was the deciding factor: it meant the live pipeline and the 2-year historical backfill could compute features identically, with no manual formula to keep in sync, and no API key required.

---

## 4) Cleaning the Data

- **Missing/`None` values** from API responses were coerced with a small helper (`_to_float`) that safely falls back to a default instead of crashing or silently corrupting downstream math.
- **Schema type consistency** was a recurring cleaning problem, not a one-time fix. Whole-number readings (e.g. `aqi=34`) caused pandas to infer `int64` on first insert, locking a Hopsworks feature group's column to `bigint` — a later decimal value (`42.5`) would then fail. The fix was to **explicitly cast every numeric column to `float64`** before every single insert, regardless of what that particular row's values looked like.
- **A second, subtler dtype issue** came from `pandas.get_dummies()` and `.dt` accessors, which return `int32`/`bool`, not the `int64` the live schema expected — this had to be forced explicitly, with an assertion added to guarantee the cast actually held (since a plain `.astype()` was observed to not always stick).
- **Timezone normalization.** Hopsworks/Hudi types timestamp columns as UTC internally. The project's chosen convention — store *naive* Lahore wall-clock time everywhere — required explicitly stripping any timezone label (`tz_localize(None)`) both when writing and when reading back, or a timestamp could silently gain a spurious UTC label and get double-converted on display (this caused a real "5 hours ahead" bug in the live dashboard before being traced and fixed).
- **Deduplication** is handled structurally rather than as a cleaning step: the feature group's primary key is `(city, timestamp)`, so re-running a script for a time window that already has data safely upserts rather than duplicating.
- **Insufficient history rows dropped.** Any row that didn't yet have enough prior history to compute a rolling feature (e.g. `aqi_rolling_mean_14d` needs 14 prior days) was dropped from the *training* dataset — necessary so the model never trains on a feature that's just a fallback default.

---

## 5) Feature Engineering

The final feature set, computed **daily** (aggregated from hourly data) for training, and **hourly** for live serving:

**Time features** (computed in `Asia/Karachi` local time, not UTC — an early bug used UTC and produced wrong hour/day values):
- `hour`, `month`, `is_weekend`
- `day_of_week` as a weekday **name** (e.g. `"monday"`), one-hot encoded for modeling

**Lag / trend features:**
- `aqi_lag_1d`, `aqi_lag_2d`, `aqi_lag_3d` (daily) / `aqi_1h_ago`, `aqi_2h_ago`, `aqi_3h_ago` (hourly, live serving)
- `aqi_change_1d` — day-over-day AQI change rate
- `aqi_rolling_mean_14d` — 14-day average AQI
- `aqi_rolling_std_7d` — 7-day AQI volatility
- `pm25_lag_1d`, `temperature_lag_1d`

**Raw pollutant & weather features:**
- `pm25`, `pm10`, `no2`, `so2`, `o3`, `co`
- `temperature`, `feels_like`, `humidity`, `pressure`, `wind_speed`

**Why daily, not hourly, for training:** the project's goal is a **3-day-ahead** forecast, which is a daily-granularity question. The live pipeline writes hourly rows (needed for fresh short-term lag features like `aqi_1h_ago`), but the training pipeline aggregates that hourly data into one row per calendar day before building lag/rolling features and targets — matching feature granularity to the actual prediction task.

---

## 6) Models I Tried, and How They Actually Did

**Approach:** 3 independent models (day+1, day+2, day+3) rather than one shared multi-output model, each with 3 candidate algorithms — **Ridge Regression, Random Forest, and XGBoost** — trained and compared, for 9 total training runs per retraining cycle.

**Real results from an early evaluation run:**

| Horizon | Winning algorithm | MAE | RMSE | R² |
|---|---|---|---|---|
| Day+1 | Random Forest | 19.14 | 27.07 | 0.568 |
| Day+2 | Random Forest | 27.44 | 36.89 | 0.185 |
| Day+3 | Ridge | 29.20 | 38.57 | 0.088 |

**What this showed:** Day+1 was reasonably close to a target range of R² ≥ 0.7 / RMSE 20–30 / MAE 10–20, but day+2 and day+3 degraded sharply. This wasn't a bug — it was diagnosed as a **structural limitation**: none of the models have access to *future* weather, only past/current values. Weather genuinely drives AQI, and predicting weather 2–3 days out from historical weather patterns alone is a much harder problem than predicting it from an actual forecast. This was documented as a known limitation rather than something to "fix" by tuning harder.

**Iteration on the feature set** (added between evaluation rounds): `aqi_rolling_mean_14d`, `aqi_rolling_std_7d` (volatility), `pm25_lag_1d`, `temperature_lag_1d` — aimed at giving the day+2/day+3 models more to work with, since hyperparameter tuning alone couldn't compensate for the missing future-weather signal.

---

## 7) How I Picked the Final Model

Selection was **per-horizon and automatic**, not a single blanket choice:

1. For each horizon, all 3 algorithms were trained on the same **time-based train/test split** (most recent N days held out as test — no shuffling, since shuffling a time series would leak future information into training).
2. Each algorithm's RMSE on the held-out test set was compared.
3. The algorithm with the **lowest RMSE for that specific horizon** was selected and registered — meaning day+1, day+2, and day+3 could each end up using a *different* algorithm, which is exactly what happened in the run above (Random Forest won day+1 and day+2; Ridge won day+3).

RMSE was chosen as the primary selection metric (over MAE or R²) because it penalizes large errors more heavily — appropriate for an air-quality forecast, where a large miss during a genuine smog spike matters more than being off by a small amount during stable air quality.

Because the training pipeline reruns daily as new data accumulates, **which algorithm wins per horizon is expected to change over time** as the growing dataset shifts what each model can learn — this is treated as a feature of the automated retraining loop, not something requiring manual override.

---

## 8) Problems I Faced and Their Solutions

This project surfaced a long list of real issues across every layer — environment setup, the feature store, model serialization, and deployment. The most significant ones:

| Area | Problem | Solution |
|---|---|---|
| **Environment setup** | Chain of `ModuleNotFoundError`s after using `pip install hopsworks --no-deps` | Installed each missing package individually (names often differ from their import names, e.g. `pyhumps` vs `import humps`) |
| **Environment setup** | `twofish`/`pyjks` failed to build (needs a C compiler) | Ultimately required installing Microsoft C++ Build Tools once disk space was freed |
| **Feature store** | Schema errors (`bigint` vs `double`, `int32` vs `bigint`) on insert | Explicit `float64`/`int64` casting before every insert, with assertions where a plain cast wasn't reliable |
| **Feature store** | Dashboard showing time 5 hours ahead of actual | Traced to Hopsworks re-labeling naive local timestamps as UTC on read; fixed by explicitly stripping timezone info on both write and read |
| **Data source** | AQICN station returning stale, unchanging AQI | Diagnosed via the station's own last-updated timestamp; ultimately dropped AQICN and consolidated on Open-Meteo |
| **Model registry** | `XGBoostError: input stream corrupted` when loading a saved model | XGBoost's own docs warn against relying on `pickle`/`joblib` for `Booster` objects; switched to XGBoost's native `save_model()`/`load_model()` format, with a marker file so loaders know which format each model uses |
| **Automation** | `ValueError: invalid literal for int()` in a GitHub Actions run | An empty GitHub Secret was still being referenced in the workflow's `env:` block, overriding the script's sensible default; removed the reference entirely |
| **Deployment** | Vercel build failing with "Could not resolve" import errors | Two separate causes: a `.gitignore` rule (`lib/`) accidentally excluding the frontend's `src/lib/` folder, and two component files tracked in git with the wrong letter-case — both worked fine on case-insensitive Windows but broke on Vercel's case-sensitive Linux build |
| **Deployment** | FastAPI Cloud: `RuntimeError: please install "fastapi[standard]"` | `requirements.txt` had plain `fastapi` instead of the `[standard]` extra FastAPI Cloud's runtime specifically requires |
| **Deployment** | `ImportError: cannot import name 'connected' from 'hsml.decorators'`, reproducible even after a full clean reinstall | Root-caused to a regression in the newest `hopsworks` release (5.0.4); pinned to the previous stable release (4.8.4) instead |
| **Deployment** | `TypeError: Metaclasses with custom tp_new are not supported`, deep inside `google.protobuf` | FastAPI Cloud's default Python (3.14) is incompatible with the compiled `protobuf` C-extension pulled in by Hopsworks' gRPC client; fixed by pinning `requires-python <3.14` in `pyproject.toml` |

---

## 9) Automation

Two GitHub Actions workflows keep the whole system running without any manual steps:

```
                              ┌───────────────────────────────┐
                              │        GitHub Actions           │
                              └───────────────────────────────┘
                                    │                    │
                     every hour, on the hour      once a day
                                    │                    │
                                    ▼                    ▼
                  ┌──────────────────────┐   ┌──────────────────────┐
                  │  feature_pipeline.yml │   │  training_pipeline.yml │
                  └──────────┬───────────┘   └──────────┬───────────┘
                              │                            │
                              ▼                            ▼
                  ┌──────────────────────┐   ┌──────────────────────┐
                  │  feature_pipeline.py   │   │  training_pipeline.py │
                  │                        │   │                        │
                  │  1. Fetch live weather │   │  1. Fetch full history │
                  │     + AQI (Open-Meteo) │   │     from Feature Store │
                  │  2. Engineer features   │   │  2. Aggregate to daily │
                  │  3. Insert 1 hourly row │   │  3. Train 3 horizons × │
                  │     into Feature Store  │   │     3 algorithms = 9   │
                  │                        │   │     runs                │
                  └──────────┬───────────┘   │  4. Register best model │
                              │                │     per horizon         │
                              ▼                └──────────┬───────────┘
                  ┌──────────────────────┐                │
                  │   Hopsworks Feature    │◄───────────────┘
                  │   Store (aqi_features) │      reads from
                  └──────────────────────┘

                                                ┌──────────────────────┐
                                                │  Hopsworks Model       │
                                                │  Registry              │
                                                │  (aqi_model_day1/2/3)  │
                                                └──────────────────────┘
```

The result: the Feature Store grows by one row every hour indefinitely, and the Model Registry gets a freshly retrained (and re-evaluated) set of models every day — both without anyone touching the system.

---

## 10) Model Training and Evaluation

**Pipeline steps** (`training_pipeline.py`):
1. Fetch the entire hourly history from the Hopsworks Feature Store
2. Aggregate to one row per calendar day
3. Build lag, rolling, and volatility features on the daily series
4. For each of the 3 horizons, build that horizon's target (`aqi` shifted forward by 1/2/3 days) and its own model-ready dataset (dropping only the rows that specific horizon actually needs to drop)
5. Split chronologically — most recent `TEST_DAYS` (default 45) days held out as the test set, everything before that as training
6. Train Ridge, Random Forest, and XGBoost on the training set
7. Evaluate all three on the test set using **RMSE, MAE, and R²**
8. Keep the lowest-RMSE algorithm for that horizon and register it

**Why a chronological split, not a random one:** shuffling a time series before splitting would let the model train on data that comes *after* some of its test examples in real time — a form of data leakage that would make evaluation numbers look artificially good and not reflect real forecasting performance.

---

## 11) Model Registry

All models are stored and versioned in the **Hopsworks Model Registry**, under three names: `aqi_model_day1`, `aqi_model_day2`, `aqi_model_day3`.

- **Every daily retraining run creates a new version** of each model — the registry keeps a full history rather than overwriting, so past versions remain available.
- **Serialization is algorithm-aware.** Ridge and Random Forest are saved via `joblib`. XGBoost models are saved via **XGBoost's own native format** (a small JSON file) instead of `joblib`/pickle, after the pickle approach was found to produce corrupted files that failed to reload (`XGBoostError: input stream corrupted`) — a fragility XGBoost's own documentation explicitly warns about. A small marker file (`model_type.txt`) travels alongside each model so any loader knows which format to expect.
- **Metrics are attached to each registered version** (RMSE, MAE, R² for that specific run), so the live-serving backend can display a model's real evaluated error alongside its prediction.
- **"Latest version" is always what gets served.** Both the training pipeline's own sanity checks and the live backend's model-loading logic fetch the highest version number for a given model name — meaning a successful daily retrain automatically becomes what the dashboard uses, with no manual promotion step.

---

## 12) Live Serving

The **FastAPI backend** (deployed on FastAPI Cloud) is the only component that holds Hopsworks credentials — the frontend never talks to Hopsworks directly.

**Endpoints:**
- `GET /api/health` — basic liveness check
- `GET /api/current` — latest AQI, category, pollutants, weather conditions
- `GET /api/trend?hours=24|48|72` — historical AQI series for the trend chart
- `GET /api/forecast` — day+1/2/3 predictions from the latest registered models
- `GET /api/explain/{horizon}` — SHAP feature contributions for a given forecast horizon

**Reliability measures built in:**
- A cached Hopsworks connection with a TTL, and automatic reconnect-and-retry if a request fails (guards against the connection going stale after a period of inactivity)
- A cached, TTL-based copy of the fetched hourly dataset, to avoid re-querying Hopsworks on every single dashboard request
- Automatic cache-clearing and re-download if a locally cached model file turns out to be corrupted

**Deployment specifics** that required real fixes to get working: pinning `hopsworks==4.8.4` (avoiding a regression in the newest release), using the `fastapi[standard]` package extra (required by FastAPI Cloud's runtime), and pinning the Python version to below 3.14 via `pyproject.toml` (the newest Python broke a compiled dependency pulled in by Hopsworks' gRPC client).

---

## 13) Dashboard

The **React frontend** (Vite + Tailwind CSS + Recharts + Framer Motion, deployed on Vercel) presents everything the backend serves:

- **Current AQI** — an animated SVG gauge, color-coded across a 4-tier scale (Low/blue, Medium/green, Above Medium/amber, High/red), with a dynamic alert banner that switches between a warning state and a "good air quality" state depending on the reading
- **Current pollutants & conditions** — PM2.5, PM10, O₃, NO₂, SO₂, CO, temperature, humidity, pressure, wind speed, each in its own stat card
- **24-hour AQI trend** — a line/area chart colored by AQI category at each point (not a single flat color), with a 24h/48h/72h range selector built into the chart itself
- **AI forecast cards** — day+1/2/3 predicted AQI, each with its own category badge and the model's evaluated RMSE
- **Predicted AQI trend graph** — a line connecting today's actual reading through the 3-day forecast
- **"Why this prediction" (SHAP panel)** — a horizontal bar chart of the top features pushing each forecast up or down, with plain-language feature names (e.g. "Current AQI", "PM2.5", "Nitrogen Dioxide (NO2)") instead of raw column names, and a horizon selector matching the forecast cards above it
- **Responsive design** — audited and fixed for mobile breakpoints (header and panel layouts that initially only worked on wider screens)

The dashboard talks to the FastAPI backend exclusively over plain JSON REST calls — no Hopsworks SDK, no credentials, and no model-loading logic live in the browser.