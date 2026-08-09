"""
training_pipeline.py

Fetches the full historical (features, targets) dataset from the Hopsworks
Feature Store, aggregates hourly data to DAILY granularity, and trains
THREE INDEPENDENT models -- one per forecast horizon (day+1, day+2, day+3).

For EACH horizon, THREE algorithms are trained and compared:
  - Ridge Regression (scikit-learn)
  - Random Forest    (scikit-learn)
  - XGBoost           (xgboost)
That's 3 horizons x 3 algorithms = 9 training runs total. The best algorithm
per horizon (lowest RMSE) is kept and registered in the Hopsworks Model
Registry -- so you end up with 3 final models: aqi_model_day1, aqi_model_day2,
aqi_model_day3, each independently trained rather than sharing one
multi-output model.

WHY DAILY, NOT HOURLY:
The project goal is "predict AQI for the next 3 days" -- a daily forecast.
feature_pipeline.py and backfill.py both write HOURLY rows (needed for
fresh lag features like aqi_1h_ago). This script is where hourly data gets
aggregated into a daily time series, which is the right granularity for a
3-day-ahead target.

PER-HORIZON DATA USAGE: each horizon builds its own model-ready dataset,
dropping only the rows it actually needs (e.g. day+1's model can use one
more day of data at the end than day+3's, since it only needs tomorrow's
value to exist, not 3 days out) -- slightly more training data per horizon
than a shared multi-output setup would allow.

Env vars required (same .env as feature_pipeline.py):
  HOPSWORKS_API_KEY    -> from Hopsworks Account Settings -> API keys
  HOPSWORKS_PROJECT    -> your Hopsworks project name
  CITY_NAME            -> e.g. "Lahore"
  TEST_DAYS            -> optional, default "45" -- most recent N days held out as test set
"""

import os
import shutil
import tempfile

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

load_dotenv()

HOPSWORKS_API_KEY = os.getenv("HOPSWORKS_API_KEY")
HOPSWORKS_PROJECT = os.getenv("HOPSWORKS_PROJECT")
CITY_NAME = os.getenv("CITY_NAME", "Lahore")
TEST_DAYS = int(os.getenv("TEST_DAYS", "45"))

FEATURE_GROUP_NAME = "aqi_features"
FEATURE_GROUP_VERSION = 1

HORIZONS = [1, 2, 3]  # days ahead

REQUIRED_ENV_VARS = ("HOPSWORKS_API_KEY", "HOPSWORKS_PROJECT")


def _require_env() -> None:
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
            + ". Check your .env file."
        )


# ---------------------------------------------------------------------------
# 1. FETCH FROM FEATURE STORE
# ---------------------------------------------------------------------------

def _connect_feature_store():
    import hopsworks

    project = hopsworks.login(
        project=HOPSWORKS_PROJECT,
        api_key_value=HOPSWORKS_API_KEY,
    )
    return project, project.get_feature_store()


def fetch_hourly_dataset(fs) -> pd.DataFrame:
    fg = fs.get_feature_group(FEATURE_GROUP_NAME, version=FEATURE_GROUP_VERSION)
    df = fg.read()
    df = df[df["city"] == CITY_NAME].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 2. HOURLY -> DAILY AGGREGATION + FEATURE ENGINEERING
# ---------------------------------------------------------------------------

def build_daily_dataset(hourly_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregates hourly rows to one row per calendar day (local time)."""
    df = hourly_df.copy()
    df["date"] = df["timestamp"].dt.date

    agg_cols = {
        "aqi": "mean",
        "pm25": "mean",
        "pm10": "mean",
        "no2": "mean",
        "so2": "mean",
        "o3": "mean",
        "co": "mean",
        "temperature": "mean",
        "feels_like": "mean",
        "humidity": "mean",
        "pressure": "mean",
        "wind_speed": "mean",
    }
    daily = df.groupby("date").agg(agg_cols).reset_index()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)

    daily["day_of_week"] = daily["date"].dt.day_name().str.lower()
    daily["month"] = daily["date"].dt.month
    daily["is_weekend"] = (daily["date"].dt.weekday >= 5).astype(int)

    # Daily-level lag/trend/volatility features
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


# ---------------------------------------------------------------------------
# 3. PER-HORIZON MODEL-READY DATASET
# ---------------------------------------------------------------------------

def build_horizon_dataset(daily: pd.DataFrame, horizon: int):
    """
    Builds a model-ready (X, y) for a SINGLE horizon, dropping only the rows
    that horizon actually needs to drop (its own target + the shared lag
    features), rather than a lowest-common-denominator drop across all 3.
    """
    df = daily.copy()
    target_col = f"aqi_next_{horizon}d"
    df[target_col] = df["aqi"].shift(-horizon)

    required_cols = [
        "aqi_lag_1d", "aqi_lag_2d", "aqi_lag_3d",
        "aqi_rolling_mean_14d", "aqi_rolling_std_7d",
        "pm25_lag_1d", "temperature_lag_1d",
        target_col,
    ]
    df = df.dropna(subset=required_cols).reset_index(drop=True)

    df = pd.get_dummies(df, columns=["day_of_week"], prefix="dow")

    exclude = {"date", "aqi", target_col}  # 'aqi' (today's value) excluded: it's the
    # base the target is built from, not a legitimate predictor at this row's
    # position -- the lagged/rolling versions of it are the real signal.
    feature_cols = [c for c in df.columns if c not in exclude]

    X = df[["date"] + feature_cols].copy()
    y = df[target_col].copy()

    return X, y, feature_cols, target_col


def time_based_split(X: pd.DataFrame, y: pd.Series, test_days: int):
    cutoff_date = X["date"].max() - pd.Timedelta(days=test_days)

    train_mask = X["date"] <= cutoff_date
    test_mask = ~train_mask

    X_train = X.loc[train_mask].drop(columns=["date"])
    X_test = X.loc[test_mask].drop(columns=["date"])
    y_train = y.loc[train_mask]
    y_test = y.loc[test_mask]

    return X_train, X_test, y_train, y_test


# ---------------------------------------------------------------------------
# 4. TRAIN + EVALUATE (3 algorithms per horizon)
# ---------------------------------------------------------------------------

def evaluate(y_true, y_pred) -> dict:
    return {
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def get_candidate_models() -> dict:
    return {
        "ridge": Pipeline([
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=1.0, random_state=42)),
        ]),
        "random_forest": RandomForestRegressor(
            n_estimators=400, max_depth=14, min_samples_leaf=2,
            random_state=42, n_jobs=-1,
        ),
        "xgboost": XGBRegressor(
            n_estimators=400, max_depth=5, learning_rate=0.03,
            subsample=0.8, colsample_bytree=0.8,
            reg_lambda=1.0, random_state=42, n_jobs=-1,
        ),
    }


def train_horizon(X_train, y_train, X_test, y_test, horizon: int) -> dict:
    """Trains all 3 candidates for one horizon, returns results for each."""
    candidates = get_candidate_models()
    results = {}

    print(f"\n=== Horizon: day+{horizon} ===")
    for name, model in candidates.items():
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        metrics = evaluate(y_test, preds)
        results[name] = {"model": model, "metrics": metrics}
        print(f"  {name:15s}  RMSE={metrics['rmse']:.2f}  MAE={metrics['mae']:.2f}  R2={metrics['r2']:.3f}")

    return results


def pick_best(results: dict):
    best_name = min(results, key=lambda name: results[name]["metrics"]["rmse"])
    print(f"  -> winning candidate: {best_name}")
    return best_name, results[best_name]


# ---------------------------------------------------------------------------
# 5. REGISTER IN HOPSWORKS MODEL REGISTRY
# ---------------------------------------------------------------------------

def register_model(project, model, model_name: str, metrics: dict, X_train: pd.DataFrame):
    mr = project.get_model_registry()

    tmp_dir = tempfile.mkdtemp()
    model_path = os.path.join(tmp_dir, "model.pkl")
    joblib.dump(model, model_path)

    hw_metrics = {k: round(v, 4) for k, v in metrics.items()}

    hw_model = mr.python.create_model(
        name=model_name,
        metrics=hw_metrics,
        description=f"AQI forecaster for {CITY_NAME}",
        input_example=X_train.iloc[[0]],
    )
    hw_model.save(tmp_dir)

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"Registered '{model_name}' (v{hw_model.version}) in Hopsworks Model Registry")
    return hw_model


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    _require_env()

    project, fs = _connect_feature_store()

    print(f"Fetching hourly data for {CITY_NAME} from '{FEATURE_GROUP_NAME}'...")
    hourly_df = fetch_hourly_dataset(fs)
    print(f"Fetched {len(hourly_df)} hourly rows")

    daily = build_daily_dataset(hourly_df)
    print(f"Aggregated to {len(daily)} daily rows")

    for horizon in HORIZONS:
        X, y, feature_cols, target_col = build_horizon_dataset(daily, horizon)
        print(f"\nHorizon day+{horizon}: {len(X)} usable rows, {len(feature_cols)} features")

        X_train, X_test, y_train, y_test = time_based_split(X, y, TEST_DAYS)
        print(f"  Train: {len(X_train)} days | Test: {len(X_test)} days")

        results = train_horizon(X_train, y_train, X_test, y_test, horizon)
        best_name, best_result = pick_best(results)

        register_model(
            project=project,
            model=best_result["model"],
            model_name=f"aqi_model_day{horizon}",
            metrics=best_result["metrics"],
            X_train=X_train,
        )


if __name__ == "__main__":
    main()