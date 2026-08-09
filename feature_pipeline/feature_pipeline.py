"""
feature_pipeline.py

Fetches current weather + pollution data for a city, engineers features,
and inserts them into a Hopsworks Feature Group.

Designed to be run:
  - Manually first (to test)
  - Then hourly via GitHub Actions / cron

NOTE ON DATA SOURCE: This pipeline uses Open-Meteo for EVERYTHING --
weather, pollutant concentrations, AND the US EPA AQI itself -- instead of
OpenWeather. Two reasons:
  1. Open-Meteo's air-quality 'current' endpoint returns a ready-made
     'us_aqi' field (US EPA methodology, 0-500 scale), computed server-side,
     so we no longer need to hand-maintain EPA breakpoint tables ourselves.
  2. backfill.py already uses Open-Meteo for historical data. Using the same
     provider + same AQI methodology here means live-served features and
     backfilled training data are computed identically -- no risk of two
     separately-maintained AQI calculations silently drifting apart.

Open-Meteo's AQI is based on CAMS atmospheric composition forecasts (a
different underlying model than OpenWeather's own AQI product), so absolute
AQI values may differ slightly from what you saw with the old OpenWeather-
based pipeline -- the EPA formula itself is standard either way.

No API key is required for Open-Meteo (non-commercial use, reasonable
request volumes).

Env vars required (put these in a local .env file, and as GitHub Secrets later):
  HOPSWORKS_API_KEY    -> from Hopsworks Account Settings -> API keys
  HOPSWORKS_PROJECT    -> your Hopsworks project name
  CITY_NAME            -> e.g. "Lahore" (used for tagging rows)
  CITY_LAT             -> e.g. "31.5497" (used for both Open-Meteo endpoints)
  CITY_LON             -> e.g. "74.3436" (used for both Open-Meteo endpoints)
  CITY_TIMEZONE        -> e.g. "Asia/Karachi" (used so hour/day/month/timestamp reflect LOCAL time, not UTC)
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

HOPSWORKS_API_KEY = os.getenv("HOPSWORKS_API_KEY")
HOPSWORKS_PROJECT = os.getenv("HOPSWORKS_PROJECT")
CITY_NAME = os.getenv("CITY_NAME", "Lahore")
CITY_LAT = float(os.getenv("CITY_LAT", "31.5497"))
CITY_LON = float(os.getenv("CITY_LON", "74.3436"))
CITY_TIMEZONE = os.getenv("CITY_TIMEZONE", "Asia/Karachi")

FEATURE_GROUP_NAME = "aqi_features"
FEATURE_GROUP_VERSION = 1

REQUIRED_ENV_VARS = (
    "HOPSWORKS_API_KEY",
    "HOPSWORKS_PROJECT",
)

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _require_env() -> None:
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
            + ". Check your .env file."
        )


def _to_float(value, default: float = 0.0) -> float:
    """Safely coerce API values (which may be None, '-', or missing) to float."""
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return float(numeric)


# ---------------------------------------------------------------------------
# 1. FETCH RAW DATA -- both from Open-Meteo
# ---------------------------------------------------------------------------

def fetch_openmeteo_pollution(lat: float, lon: float) -> dict:
    """
    Fetch current pollutant concentrations AND the ready-made US EPA AQI
    from Open-Meteo's Air Quality API. 'us_aqi' is computed server-side by
    Open-Meteo using the standard EPA breakpoint methodology (0-500 scale) --
    the same thing calculate_us_aqi() used to compute manually.
    """
    resp = requests.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "us_aqi,pm2_5,pm10,nitrogen_dioxide,sulphur_dioxide,ozone,carbon_monoxide",
        },
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()

    current = payload.get("current")
    if not current:
        raise RuntimeError(f"Open-Meteo air quality API returned no current data: {payload}")

    return {
        "aqi": current.get("us_aqi"),
        "pm25": current.get("pm2_5"),
        "pm10": current.get("pm10"),
        "no2": current.get("nitrogen_dioxide"),
        "so2": current.get("sulphur_dioxide"),
        "o3": current.get("ozone"),
        "co": current.get("carbon_monoxide"),
    }


def fetch_openmeteo_weather(lat: float, lon: float) -> dict:
    """Fetch current weather readings from Open-Meteo's Forecast API."""
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,surface_pressure,wind_speed_10m",
        },
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()

    current = payload.get("current")
    if not current:
        raise RuntimeError(f"Open-Meteo forecast API returned no current data: {payload}")

    return {
        "temperature": current.get("temperature_2m"),
        "feels_like": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "pressure": current.get("surface_pressure"),
        "wind_speed": current.get("wind_speed_10m"),
    }


# ---------------------------------------------------------------------------
# 2. FEATURE ENGINEERING
# ---------------------------------------------------------------------------

def build_time_features(local_ts: datetime) -> dict:
    """
    IMPORTANT: pass in LOCAL time (already converted via ZoneInfo), not UTC.
    Using UTC here was the earlier bug -- hour/day_of_week/is_weekend would
    reflect the wrong day/time whenever local time and UTC fall on different
    calendar days or noticeably different hours.

    day_of_week is returned as a lowercase weekday name (e.g. "monday")
    rather than an integer.
    """
    return {
        "hour": local_ts.hour,
        "day_of_week": DAY_NAMES[local_ts.weekday()],  # "monday" ... "sunday"
        "month": local_ts.month,
        "is_weekend": int(local_ts.weekday() >= 5),
    }


def get_recent_history(fs, hours: int = 24) -> pd.DataFrame:
    """
    Read recent rows already stored in Hopsworks for this city, so we can
    compute lag features (1h/2h/3h ago). Returns an empty DataFrame if the
    feature group doesn't exist yet or has no data (first run) -- this is
    expected and NOT an error.
    """
    try:
        fg = fs.get_feature_group(FEATURE_GROUP_NAME, version=FEATURE_GROUP_VERSION)
        if fg is None:
            return pd.DataFrame()

        df = fg.read()
        if df.empty:
            return df

        df = df[df["city"] == CITY_NAME].copy()
        if df.empty:
            return df

        # Timestamps are stored as naive Lahore wall-clock time (see
        # build_feature_row), so parse them naively here too -- don't treat
        # them as UTC, or lag lookups will be off by the UTC offset.
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        if df["timestamp"].dt.tz is not None:
            df["timestamp"] = df["timestamp"].dt.tz_localize(None)
        df = df.sort_values("timestamp")

        cutoff = pd.Timestamp.now(tz=CITY_TIMEZONE).replace(tzinfo=None) - pd.Timedelta(hours=hours)
        return df[df["timestamp"] >= cutoff]

    except Exception as e:
        print(f"No prior history found yet (expected on first run): {e}")
        return pd.DataFrame()


def compute_lag_features(history: pd.DataFrame, current_aqi: float) -> dict:
    """
    Uses historical rows (if any) to compute:
      - aqi_1h_ago, aqi_2h_ago, aqi_3h_ago
      - aqi_change (current - most recent previous reading)
    Falls back to current values if not enough history exists yet,
    so early runs don't crash -- they just aren't very informative yet.
    """
    current_aqi = _to_float(current_aqi)

    if history.empty:
        return {
            "aqi_1h_ago": current_aqi,
            "aqi_2h_ago": current_aqi,
            "aqi_3h_ago": current_aqi,
            "aqi_change": 0.0,
        }

    now = pd.Timestamp.now(tz=CITY_TIMEZONE).replace(tzinfo=None)

    def value_closest_to(hours_ago: int, col: str, fallback: float) -> float:
        if col not in history.columns or history.empty:
            return fallback
        target = now - pd.Timedelta(hours=hours_ago)
        idx = (history["timestamp"] - target).abs().idxmin()
        return _to_float(history.loc[idx, col], default=fallback)

    aqi_1h = value_closest_to(1, "aqi", current_aqi)
    aqi_2h = value_closest_to(2, "aqi", current_aqi)
    aqi_3h = value_closest_to(3, "aqi", current_aqi)

    last_row = history.iloc[-1]
    aqi_change = current_aqi - _to_float(last_row.get("aqi"), default=current_aqi)

    return {
        "aqi_1h_ago": aqi_1h,
        "aqi_2h_ago": aqi_2h,
        "aqi_3h_ago": aqi_3h,
        "aqi_change": float(aqi_change),
    }


# ---------------------------------------------------------------------------
# 3. MAIN PIPELINE
# ---------------------------------------------------------------------------

def _connect_feature_store():
    import hopsworks  # imported lazily so the rest of the script can be
    # unit-tested / linted without hopsworks installed

    project = hopsworks.login(
        project=HOPSWORKS_PROJECT,
        api_key_value=HOPSWORKS_API_KEY,
    )
    return project.get_feature_store()


def _get_or_create_feature_group(fs):
    return fs.get_or_create_feature_group(
        name=FEATURE_GROUP_NAME,
        version=FEATURE_GROUP_VERSION,
        description="Hourly AQI + weather features per city",
        primary_key=["city", "timestamp"],
        event_time="timestamp",
        online_enabled=True,
        time_travel_format="HUDI",
    )


def build_feature_row(fs=None) -> pd.DataFrame:
    """Fetch raw data, engineer all features, return a 1-row DataFrame."""
    utc_now = datetime.now(timezone.utc)
    local_now = utc_now.astimezone(ZoneInfo(CITY_TIMEZONE))

    pollution_data = fetch_openmeteo_pollution(CITY_LAT, CITY_LON)
    weather = fetch_openmeteo_weather(CITY_LAT, CITY_LON)
    time_feats = build_time_features(local_now)

    current_aqi = _to_float(pollution_data.get("aqi"))

    history = get_recent_history(fs, hours=24) if fs is not None else pd.DataFrame()
    lag_feats = compute_lag_features(history, current_aqi=current_aqi)

    # Hopsworks/Hudi stores timestamps internally as UTC. If we pass a
    # timezone-aware datetime, it gets silently converted back to UTC on
    # write -- which is exactly the "5 hours behind" bug. To make the
    # displayed column actually show Lahore wall-clock time, we strip the
    # tzinfo here and store the raw Lahore local numbers as a naive
    # datetime, so there's nothing left for Hopsworks to convert.
    local_now_naive = local_now.replace(tzinfo=None)

    row = {
        "city": CITY_NAME,
        "timestamp": local_now_naive,
        **pollution_data,
        **weather,
        **time_feats,
        **lag_feats,
    }

    df = pd.DataFrame([row])

    # day_of_week is a string (weekday name), so it's excluded from
    # numeric coercion below along with city/timestamp.
    numeric_cols = [c for c in df.columns if c not in ("city", "timestamp", "day_of_week")]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Force these specific columns to float64 explicitly. Without this, pandas
    # may infer int64 for a row where the value happens to be a whole number,
    # which locks the Hopsworks feature group schema to 'bigint' on first
    # creation -- then a later decimal value fails schema validation.
    float_cols = [
        "aqi", "pm25", "pm10", "no2", "so2", "o3", "co",
        "temperature", "feels_like",
        "humidity", "pressure", "wind_speed",
        "aqi_1h_ago", "aqi_2h_ago", "aqi_3h_ago", "aqi_change",
    ]
    for col in float_cols:
        if col in df.columns:
            df[col] = df[col].astype("float64")

    return df


def push_to_hopsworks(df: pd.DataFrame, fs=None):
    if fs is None:
        _require_env()
        fs = _connect_feature_store()

    fg = _get_or_create_feature_group(fs)
    fg.insert(df)
    print(f"Inserted {len(df)} row(s) into '{FEATURE_GROUP_NAME}' (v{FEATURE_GROUP_VERSION})")
    return fs


def main():
    _require_env()

    fs = _connect_feature_store()

    df = build_feature_row(fs=fs)
    print("Built feature row:")
    print(df.T)

    push_to_hopsworks(df, fs=fs)


if __name__ == "__main__":
    main()