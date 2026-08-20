"""
backend/main.py

FastAPI backend for the AQI Predictor React frontend. All Hopsworks
credentials and SDK calls live HERE, never in the browser -- the React app
only ever talks to this API over plain JSON.

Run with:
  uvicorn backend.main:app --reload --port 8000

Env vars required (same .env as the other scripts):
  HOPSWORKS_API_KEY    -> from Hopsworks Account Settings -> API keys
  HOPSWORKS_PROJECT    -> your Hopsworks project name
  CITY_NAME            -> e.g. "Lahore"
  FRONTEND_ORIGIN       -> optional, default "http://localhost:5173" (Vite dev server)
"""

import os
import time
from datetime import timedelta

import joblib
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

HOPSWORKS_API_KEY = os.getenv("HOPSWORKS_API_KEY")
HOPSWORKS_PROJECT = os.getenv("HOPSWORKS_PROJECT")
CITY_NAME = os.getenv("CITY_NAME", "Lahore")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

FEATURE_GROUP_NAME = "aqi_features"
FEATURE_GROUP_VERSION = 1
HORIZONS = [1, 2, 3]

CONNECTION_TTL = 1800  # seconds -- reconnect periodically to avoid stale gRPC connections
DATA_TTL = 600  # seconds -- how long a fetched hourly dataset is reused before refetching

app = FastAPI(title="AQI Predictor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "https://aqi-predictor-green.vercel.app","http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_env() -> None:
    if not HOPSWORKS_API_KEY or not HOPSWORKS_PROJECT:
        raise HTTPException(500, "Server is missing HOPSWORKS_API_KEY / HOPSWORKS_PROJECT.")


def _safe_round(val, digits: int = 1):
    if val is None or pd.isna(val):
        return None
    return round(float(val), digits)


# ---------------------------------------------------------------------------
# HOPSWORKS CONNECTION (module-level cache, refreshed on a TTL)
# ---------------------------------------------------------------------------

_connection_cache = {"project": None, "fs": None, "mr": None, "ts": 0.0}


def get_connection():
    now = time.time()
    if _connection_cache["fs"] is None or (now - _connection_cache["ts"]) > CONNECTION_TTL:
        import hopsworks

        project = hopsworks.login(project=HOPSWORKS_PROJECT, api_key_value=HOPSWORKS_API_KEY)
        _connection_cache.update({
            "project": project,
            "fs": project.get_feature_store(),
            "mr": project.get_model_registry(),
            "ts": now,
        })
    return _connection_cache["project"], _connection_cache["fs"], _connection_cache["mr"]


# ---------------------------------------------------------------------------
# DATA FETCHING (module-level TTL cache -- avoids hammering Hopsworks on
# every frontend request/poll)
# ---------------------------------------------------------------------------

_data_cache = {"df": None, "ts": 0.0}


def fetch_hourly_dataset() -> pd.DataFrame:
    now = time.time()
    if _data_cache["df"] is not None and (now - _data_cache["ts"]) < DATA_TTL:
        return _data_cache["df"]

    _, fs, _ = get_connection()
    try:
        fg = fs.get_feature_group(FEATURE_GROUP_NAME, version=FEATURE_GROUP_VERSION)
        df = fg.read()
    except Exception:
        # Underlying Hopsworks gRPC connection can go stale after idle time.
        # Force a fresh reconnect and retry once before giving up.
        _connection_cache["ts"] = 0.0
        _, fs2, _ = get_connection()
        fg = fs2.get_feature_group(FEATURE_GROUP_NAME, version=FEATURE_GROUP_VERSION)
        df = fg.read()

    df = df[df["city"] == CITY_NAME].copy()

    # Timestamps are stored as naive Lahore wall-clock time by design (see
    # feature_pipeline.py). Hopsworks/Hudi types the column as UTC
    # internally though, so pandas can return it back as tz-AWARE (UTC-
    # labeled) even though the actual digits are Lahore local time. If we
    # don't strip that label, the ISO string sent to the frontend carries a
    # spurious "+00:00", and the browser then converts it AGAIN to the
    # viewer's local zone -- adding a second, incorrect offset on top of an
    # already-correct value. Stripping tzinfo here guarantees a plain,
    # offset-free ISO string that the frontend displays as-is.
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)

    df = df.sort_values("timestamp").reset_index(drop=True)

    _data_cache.update({"df": df, "ts": now})
    return df


# ---------------------------------------------------------------------------
# DAILY AGGREGATION -- identical to training_pipeline.py / predict.py.
# Keep these in sync, or forecasts will use different features than trained.
# ---------------------------------------------------------------------------

def build_daily_dataset(hourly_df: pd.DataFrame) -> pd.DataFrame:
    df = hourly_df.copy()
    df["date"] = df["timestamp"].dt.date

    agg_cols = {
        "aqi": "mean", "pm25": "mean", "pm10": "mean", "no2": "mean",
        "so2": "mean", "o3": "mean", "co": "mean", "temperature": "mean",
        "feels_like": "mean", "humidity": "mean", "pressure": "mean",
        "wind_speed": "mean",
    }
    daily = df.groupby("date").agg(agg_cols).reset_index()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)

    daily["day_of_week"] = daily["date"].dt.day_name().str.lower()
    daily["month"] = daily["date"].dt.month
    daily["is_weekend"] = (daily["date"].dt.weekday >= 5).astype(int)

    daily["aqi_lag_1d"] = daily["aqi"].shift(1)
    daily["aqi_lag_2d"] = daily["aqi"].shift(2)
    daily["aqi_lag_3d"] = daily["aqi"].shift(3)
    daily["aqi_change_1d"] = daily["aqi"] - daily["aqi"].shift(1)
    daily["aqi_rolling_mean_3d"] = daily["aqi"].shift(1).rolling(window=3).mean()
    daily["aqi_rolling_mean_7d"] = daily["aqi"].shift(1).rolling(window=7).mean()
    daily["aqi_rolling_mean_14d"] = daily["aqi"].shift(1).rolling(window=14).mean()
    daily["aqi_rolling_std_7d"] = daily["aqi"].shift(1).rolling(window=7).std()
    daily["pm25_lag_1d"] = daily["pm25"].shift(1)
    daily["temperature_lag_1d"] = daily["temperature"].shift(1)

    return daily


def build_latest_feature_row(daily: pd.DataFrame):
    df = daily.copy()
    required_cols = [
        "aqi_lag_1d", "aqi_lag_2d", "aqi_lag_3d",
        "aqi_rolling_mean_14d", "aqi_rolling_std_7d",
        "pm25_lag_1d", "temperature_lag_1d",
    ]
    df = df.dropna(subset=required_cols).reset_index(drop=True)
    if df.empty:
        return None, None

    df = pd.get_dummies(df, columns=["day_of_week"], prefix="dow", dtype=int)
    exclude = {"date", "aqi"}
    feature_cols = [c for c in df.columns if c not in exclude]

    latest_row = df.iloc[[-1]]
    reference_date = latest_row["date"].iloc[0]
    X_today = latest_row[feature_cols].copy()
    return X_today, reference_date


def build_feature_history(daily: pd.DataFrame):
    """
    Same feature construction as build_latest_feature_row(), but returns
    ALL valid rows (not just the most recent) -- used as SHAP's background
    reference distribution rather than for prediction.
    """
    df = daily.copy()
    required_cols = [
        "aqi_lag_1d", "aqi_lag_2d", "aqi_lag_3d",
        "aqi_rolling_mean_14d", "aqi_rolling_std_7d",
        "pm25_lag_1d", "temperature_lag_1d",
    ]
    df = df.dropna(subset=required_cols).reset_index(drop=True)
    if df.empty:
        return None

    df = pd.get_dummies(df, columns=["day_of_week"], prefix="dow", dtype=int)
    exclude = {"date", "aqi"}
    feature_cols = [c for c in df.columns if c not in exclude]
    return df[feature_cols].copy()


# Friendly display names for the SHAP explanation UI. Any column starting
# with "dow_" (one-hot day-of-week dummies) is aggregated into a single
# "Day of Week" bar rather than shown as 7 separate near-zero bars.
FEATURE_DISPLAY_NAMES = {
    "aqi_lag_1d": "Current AQI",
    "aqi_lag_2d": "AQI (2 Days Ago)",
    "aqi_lag_3d": "AQI (3 Days Ago)",
    "aqi_change_1d": "AQI Change Rate",
    "aqi_rolling_mean_3d": "3-Day Avg AQI",
    "aqi_rolling_mean_7d": "7-Day Avg AQI",
    "aqi_rolling_mean_14d": "14-Day Avg AQI",
    "aqi_rolling_std_7d": "AQI Volatility (7d)",
    "pm25_lag_1d": "PM2.5 (Previous Day)",
    "temperature_lag_1d": "Temperature (Previous Day)",
    "pm25": "PM2.5",
    "pm10": "PM10",
    "no2": "Nitrogen Dioxide (NO\u2082)",
    "so2": "Sulfur Dioxide (SO\u2082)",
    "o3": "Ozone (O\u2083)",
    "co": "Carbon Monoxide (CO)",
    "temperature": "Temperature",
    "feels_like": "Feels Like",
    "humidity": "Humidity",
    "pressure": "Pressure",
    "wind_speed": "Wind Speed",
    "month": "Month",
    "is_weekend": "Weekend",
}


def _display_name(col: str) -> str:
    if col.startswith("dow_"):
        return "Day of Week"
    return FEATURE_DISPLAY_NAMES.get(col, col)


# ---------------------------------------------------------------------------
# AQI CATEGORY -- 4-tier scheme: Low (blue) / Medium (green) /
# Above Medium (amber) / High (red)
# ---------------------------------------------------------------------------

def aqi_category(aqi: float):
    if aqi <= 50:
        return "Low", "#3B82F6", "Air quality is good. Enjoy outdoor activities as normal."
    elif aqi <= 100:
        return "Medium", "#22C55E", "Air quality is acceptable for most people."
    elif aqi <= 150:
        return "Above Medium", "#EAB308", "Sensitive groups should limit prolonged outdoor exertion."
    else:
        return "High", "#EF4444", "Air quality may affect everyone. Limit outdoor exposure where possible."


# ---------------------------------------------------------------------------
# MODEL LOADING (module-level cache, keyed by name:version)
# ---------------------------------------------------------------------------

_model_cache = {}


def _load_model_from_dir(download_dir: str):
    type_path = os.path.join(download_dir, "model_type.txt")
    model_type = "sklearn"
    if os.path.exists(type_path):
        with open(type_path) as f:
            model_type = f.read().strip()

    if model_type == "xgboost":
        from xgboost import XGBRegressor
        model = XGBRegressor()
        model.load_model(os.path.join(download_dir, "model.json"))
    else:
        model = joblib.load(os.path.join(download_dir, "model.pkl"))

    return model


def get_latest_model(model_name: str):
    """Returns (model, metrics, version) for the latest version of model_name, cached."""
    _, _, mr = get_connection()
    models = mr.get_models(name=model_name)
    if not models:
        return None, None, None

    latest = max(models, key=lambda m: m.version)
    cache_key = f"{model_name}:{latest.version}"
    if cache_key in _model_cache:
        model, metrics = _model_cache[cache_key]
        return model, metrics, latest.version

    hw_model = mr.get_model(name=model_name, version=latest.version)
    try:
        download_dir = hw_model.download()
        model = _load_model_from_dir(download_dir)
    except Exception:
        # Safety net against a corrupted local download cache.
        try:
            hw_model.clear_cache()
        except Exception:
            pass
        download_dir = hw_model.download()
        model = _load_model_from_dir(download_dir)

    result = (model, hw_model.training_metrics)
    _model_cache[cache_key] = result
    return model, hw_model.training_metrics, latest.version


def predict_horizon(model, X_today: pd.DataFrame) -> float:
    X = X_today.copy()
    expected_cols = getattr(model, "feature_names_in_", None)
    if expected_cols is not None:
        X = X.reindex(columns=list(expected_cols), fill_value=0)
    return float(model.predict(X)[0])


# ---------------------------------------------------------------------------
# SHAP EXPLANATIONS (cached per model name:version, same key as the model cache)
# ---------------------------------------------------------------------------

_explainer_cache = {}


def get_explainer(model_name: str, version: int, model, X_background: pd.DataFrame):
    import shap
    from sklearn.ensemble import RandomForestRegressor
    from xgboost import XGBRegressor

    cache_key = f"{model_name}:{version}"
    if cache_key in _explainer_cache:
        return _explainer_cache[cache_key]

    if isinstance(model, (RandomForestRegressor, XGBRegressor)):
        # Tree models: TreeExplainer computes EXACT Shapley values directly
        # from the tree structure -- fast, and doesn't need background data.
        explainer = shap.TreeExplainer(model)
    else:
        # Anything else (the Ridge pipeline, which includes a scaling step)
        # falls back to a model-agnostic explainer built from the model's
        # own .predict() -- works regardless of internal structure, at the
        # cost of being slower. Fine here since this only runs on-demand.
        background = X_background.sample(n=min(50, len(X_background)), random_state=42)
        explainer = shap.Explainer(model.predict, background)

    _explainer_cache[cache_key] = explainer
    return explainer


def compute_shap_explanation(model_name: str, version: int, model, X_today: pd.DataFrame, X_background: pd.DataFrame, prediction: float):
    from sklearn.ensemble import RandomForestRegressor
    from xgboost import XGBRegressor

    expected_cols = getattr(model, "feature_names_in_", None)
    X = X_today.copy()
    X_bg = X_background.copy()
    if expected_cols is not None:
        X = X.reindex(columns=list(expected_cols), fill_value=0)
        X_bg = X_bg.reindex(columns=list(expected_cols), fill_value=0)

    explainer = get_explainer(model_name, version, model, X_bg)

    if isinstance(model, (RandomForestRegressor, XGBRegressor)):
        raw = explainer.shap_values(X)  # shape (1, n_features) for a single-row X
        raw_values = dict(zip(X.columns, raw[0]))
    else:
        explanation = explainer(X)
        raw_values = dict(zip(X.columns, explanation.values[0]))

    # Aggregate one-hot day-of-week dummies into a single "Day of Week" bar
    aggregated = {}
    for col, val in raw_values.items():
        label = _display_name(col)
        aggregated[label] = aggregated.get(label, 0.0) + float(val)

    contributions = [
        {"feature": label, "shap_value": round(val, 2), "direction": "increase" if val >= 0 else "decrease"}
        for label, val in aggregated.items()
    ]
    # Sort by absolute magnitude ascending (smallest at top, largest/most
    # influential at the bottom) -- matches the reference chart layout.
    contributions.sort(key=lambda c: abs(c["shap_value"]))

    increases = [c for c in contributions if c["shap_value"] > 0]
    decreases = [c for c in contributions if c["shap_value"] < 0]
    top_increase = max(increases, key=lambda c: c["shap_value"]) if increases else None
    top_decrease = min(decreases, key=lambda c: c["shap_value"]) if decreases else None

    return {
        "predicted_aqi": round(prediction, 1),
        "top_increase": top_increase,
        "top_decrease": top_decrease,
        "contributions": contributions,
    }


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "city": CITY_NAME}


@app.get("/api/current")
def get_current():
    _require_env()
    df = fetch_hourly_dataset()
    if df.empty:
        raise HTTPException(404, "No data available yet for this city.")

    latest = df.iloc[-1]
    aqi = float(latest["aqi"])
    label, color, guidance = aqi_category(aqi)

    return {
        "city": CITY_NAME,
        "timestamp": latest["timestamp"].isoformat(),
        "aqi": _safe_round(aqi),
        "category": label,
        "color": color,
        "guidance": guidance,
        "aqi_change": _safe_round(latest.get("aqi_change", 0.0)),
        "pollutants": {
            "pm25": _safe_round(latest.get("pm25")),
            "pm10": _safe_round(latest.get("pm10")),
            "o3": _safe_round(latest.get("o3")),
            "no2": _safe_round(latest.get("no2")),
            "so2": _safe_round(latest.get("so2")),
            "co": _safe_round(latest.get("co")),
        },
        "conditions": {
            "temperature": _safe_round(latest.get("temperature")),
            "humidity": _safe_round(latest.get("humidity")),
            "pressure": _safe_round(latest.get("pressure")),
            "wind_speed": _safe_round(latest.get("wind_speed")),
        },
    }


TREND_HOURS = [24, 48, 72]


@app.get("/api/trend")
def get_trend(hours: int = 24):
    _require_env()
    if hours not in TREND_HOURS:
        raise HTTPException(400, f"hours must be one of {TREND_HOURS}")

    df = fetch_hourly_dataset()
    if df.empty:
        raise HTTPException(404, "No data available yet for this city.")

    recent = df.tail(hours)
    aqis = recent["aqi"]

    points = [
        {"timestamp": row["timestamp"].isoformat(), "aqi": _safe_round(row["aqi"])}
        for _, row in recent.iterrows()
    ]

    return {
        "hours": hours,
        "points": points,
        "current": _safe_round(aqis.iloc[-1]),
        "avg": _safe_round(aqis.mean()),
        "min": _safe_round(aqis.min()),
        "max": _safe_round(aqis.max()),
    }


@app.get("/api/forecast")
def get_forecast():
    _require_env()
    df = fetch_hourly_dataset()
    if df.empty:
        raise HTTPException(404, "No data available yet for this city.")

    daily = build_daily_dataset(df)
    X_today, reference_date = build_latest_feature_row(daily)

    if X_today is None:
        raise HTTPException(422, "Not enough historical data yet for a forecast (need ~14+ days).")

    current_aqi = float(df.iloc[-1]["aqi"])
    results = []

    for horizon in HORIZONS:
        model_name = f"aqi_model_day{horizon}"
        model, metrics, _ = get_latest_model(model_name)
        if model is None:
            continue

        prediction = predict_horizon(model, X_today)
        label, color, _ = aqi_category(prediction)
        target_date = reference_date + timedelta(days=horizon)

        results.append({
            "horizon": horizon,
            "date": target_date.date().isoformat(),
            "prediction": _safe_round(prediction),
            "category": label,
            "color": color,
            "rmse": _safe_round(metrics.get("rmse")) if metrics else None,
        })

    if not results:
        raise HTTPException(404, "No trained models found in the Model Registry yet.")

    trend_direction = "improving" if results[-1]["prediction"] <= current_aqi else "worsening"

    return {
        "reference_date": reference_date.date().isoformat(),
        "current_aqi": _safe_round(current_aqi),
        "forecast": results,
        "trend_direction": trend_direction,
    }


@app.get("/api/explain/{horizon}")
def explain_forecast(horizon: int):
    _require_env()
    if horizon not in HORIZONS:
        raise HTTPException(400, f"horizon must be one of {HORIZONS}")

    df = fetch_hourly_dataset()
    if df.empty:
        raise HTTPException(404, "No data available yet for this city.")

    daily = build_daily_dataset(df)
    X_today, reference_date = build_latest_feature_row(daily)
    X_background = build_feature_history(daily)

    if X_today is None or X_background is None or len(X_background) < 5:
        raise HTTPException(422, "Not enough historical data yet to compute an explanation.")

    model_name = f"aqi_model_day{horizon}"
    model, _, version = get_latest_model(model_name)
    if model is None:
        raise HTTPException(404, f"No trained model found for day+{horizon}.")

    prediction = predict_horizon(model, X_today)
    explanation = compute_shap_explanation(model_name, version, model, X_today, X_background, prediction)
    explanation["horizon"] = horizon

    return explanation