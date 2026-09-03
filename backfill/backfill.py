"""
backfill.py

this pipeline fetches 2 years of historical data (weather + air quality) for the city from Open-Meteo (no API),
and engineers the exact same features as in feature_pipeline.py , adn inserts them into HopsWorks feature group.


Data sources (both free, no API key, no rate-limit key required for
non-commercial use up to 10,000 requests/day):
  Weather:    https://archive-api.open-meteo.com/v1/archive
  Pollutants: https://air-quality-api.open-meteo.com/v1/air-quality

NOTE ON AQI: kept IDENTICAL to feature_pipeline.py on purpose -- requests
the 'us_aqi' hourly variable directly from Open-Meteo's Air Quality API
(same endpoint, same historical data, same US EPA methodology, computed
server-side by Open-Meteo). This guarantees the backfilled training data
and the live-served features use the exact same AQI computation.

Env vars required (same .env as feature_pipeline.py):
  HOPSWORKS_API_KEY             -> from Hopsworks Account Settings -> API keys
  HOPSWORKS_PROJECT             -> your Hopsworks project name
  CITY_NAME                     -> e.g. "Lahore" (used for tagging rows)
  CITY_LAT                      -> e.g. "31.5497"
  CITY_LON                      -> e.g. "74.3436"
  CITY_TIMEZONE                 -> e.g. "Asia/Karachi" (used so hour/day/month/timestamp reflect LOCAL time)
  BACKFILL_YEARS                -> optional, default "2"
  BACKFILL_FEATURE_GROUP_NAME   -> optional, default "aqi_features_backfill". Set to
                                    "aqi_features" to insert directly into the LIVE group.
  BACKFILL_FEATURE_GROUP_VERSION -> optional, default "1"
"""

import os
from datetime import date, datetime, timedelta
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
BACKFILL_YEARS = int(os.getenv("BACKFILL_YEARS", "2"))

FEATURE_GROUP_NAME = os.getenv("BACKFILL_FEATURE_GROUP_NAME", "aqi_features_backfill")
FEATURE_GROUP_VERSION = int(os.getenv("BACKFILL_FEATURE_GROUP_VERSION", "1"))

REQUIRED_ENV_VARS = ("HOPSWORKS_API_KEY", "HOPSWORKS_PROJECT")

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _require_env() -> None:
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
            + ". Check your .env file."
        )


# ---------------------------------------------------------------------------
# 1. FETCH HISTORICAL DATA FROM OPEN-METEO
# ---------------------------------------------------------------------------

def fetch_historical_weather(lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    """Fetch hourly historical weather from Open-Meteo's Archive API."""
    resp = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m,surface_pressure,wind_speed_10m",
            "timezone": "UTC",
        },
        timeout=60,
    )
    resp.raise_for_status()
    payload = resp.json()

    hourly = payload.get("hourly", {})
    if not hourly or "time" not in hourly:
        raise RuntimeError(f"Open-Meteo weather archive returned no data: {payload}")

    df = pd.DataFrame({
        "timestamp": pd.to_datetime(hourly["time"], utc=True),
        "temperature": hourly.get("temperature_2m"),
        "feels_like": hourly.get("apparent_temperature"),
        "humidity": hourly.get("relative_humidity_2m"),
        "pressure": hourly.get("surface_pressure"),
        "wind_speed": hourly.get("wind_speed_10m"),
    })
    return df


def fetch_historical_pollution(lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    """
    Fetch hourly historical pollutant concentrations AND the ready-made US
    EPA AQI ('us_aqi') from Open-Meteo's Air Quality API.
    """
    resp = requests.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": "us_aqi,pm2_5,pm10,nitrogen_dioxide,sulphur_dioxide,ozone,carbon_monoxide",
            "timezone": "UTC",
        },
        timeout=60,
    )
    resp.raise_for_status()
    payload = resp.json()

    hourly = payload.get("hourly", {})
    if not hourly or "time" not in hourly:
        raise RuntimeError(f"Open-Meteo air quality archive returned no data: {payload}")

    df = pd.DataFrame({
        "timestamp": pd.to_datetime(hourly["time"], utc=True),
        "aqi": hourly.get("us_aqi"),
        "pm25": hourly.get("pm2_5"),
        "pm10": hourly.get("pm10"),
        "no2": hourly.get("nitrogen_dioxide"),
        "so2": hourly.get("sulphur_dioxide"),
        "o3": hourly.get("ozone"),
        "co": hourly.get("carbon_monoxide"),
    })
    return df


# ---------------------------------------------------------------------------
# 2. FEATURE ENGINEERING (vectorized across the whole history at once)
# ---------------------------------------------------------------------------

def build_backfill_dataframe(weather_df: pd.DataFrame, pollution_df: pd.DataFrame) -> pd.DataFrame:
    df = pd.merge(weather_df, pollution_df, on="timestamp", how="inner")
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Drop rows with no AQI reading -- can't build a useful training row
    df = df.dropna(subset=["aqi"]).reset_index(drop=True)

    # Local-time features (city timezone, NOT UTC)
    local_ts = df["timestamp"].dt.tz_convert(ZoneInfo(CITY_TIMEZONE))
    df["hour"] = local_ts.dt.hour
    df["day_of_week"] = local_ts.dt.day_name().str.lower()  # "monday" ... "sunday"
    df["month"] = local_ts.dt.month
    df["is_weekend"] = (local_ts.dt.weekday >= 5).astype(int)

    # Overwrite the UTC timestamp with the naive Lahore local timestamp,
    # matching feature_pipeline.py's storage convention exactly.
    df["timestamp"] = local_ts.dt.tz_localize(None)

    # Lag + change features, vectorized via shift() on the sorted hourly series
    df["aqi_1h_ago"] = df["aqi"].shift(1)
    df["aqi_2h_ago"] = df["aqi"].shift(2)
    df["aqi_3h_ago"] = df["aqi"].shift(3)
    df["aqi_change"] = df["aqi"] - df["aqi"].shift(1)

    for col in ("aqi_1h_ago", "aqi_2h_ago", "aqi_3h_ago"):
        df[col] = df[col].fillna(df["aqi"])
    df["aqi_change"] = df["aqi_change"].fillna(0.0)

    df["city"] = CITY_NAME

    float_cols = [
        "aqi", "pm25", "pm10", "no2", "so2", "o3", "co",
        "temperature", "feels_like",
        "humidity", "pressure", "wind_speed",
        "aqi_1h_ago", "aqi_2h_ago", "aqi_3h_ago", "aqi_change",
    ]
    for col in float_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    # IMPORTANT: pandas' .dt.hour / .dt.month accessors return int32, but the
    # live feature group's schema (established by feature_pipeline.py) has
    # these columns typed as 'bigint' (int64). Without this explicit cast,
    # inserting into the SAME feature group as the live pipeline raises
    # "Features are not compatible with Feature Group schema" -- int vs
    # bigint. We cast via the underlying numpy array (not just .astype() on
    # the Series) and then hard-verify it, since a plain .astype("int64")
    # has been observed to not always stick through pandas' internal
    # optimizations on every platform/version.
    import numpy as np
    int_cols = ["hour", "month", "is_weekend"]
    for col in int_cols:
        df[col] = pd.array(df[col].to_numpy(dtype=np.int64), dtype="int64")
        assert df[col].dtype == "int64", (
            f"Column '{col}' failed to cast to int64 -- got {df[col].dtype} instead. "
            "This WILL cause a Hopsworks schema mismatch on insert."
        )
    print(f"Confirmed dtypes -- hour: {df['hour'].dtype}, month: {df['month'].dtype}, is_weekend: {df['is_weekend'].dtype}")

    ordered_cols = [
        "city", "timestamp", "aqi",
        "pm25", "pm10", "no2", "so2", "o3", "co",
        "temperature", "feels_like",
        "humidity", "pressure", "wind_speed",
        "hour", "day_of_week", "month", "is_weekend",
        "aqi_1h_ago", "aqi_2h_ago", "aqi_3h_ago", "aqi_change",
    ]
    return df[ordered_cols]


# ---------------------------------------------------------------------------
# 3. PUSH TO HOPSWORKS
# ---------------------------------------------------------------------------

def _connect_feature_store():
    import hopsworks

    project = hopsworks.login(
        project=HOPSWORKS_PROJECT,
        api_key_value=HOPSWORKS_API_KEY,
    )
    return project.get_feature_store()


def push_to_hopsworks(df: pd.DataFrame):
    fs = _connect_feature_store()
    fg = fs.get_or_create_feature_group(
        name=FEATURE_GROUP_NAME,
        version=FEATURE_GROUP_VERSION,
        description="Hourly AQI + weather features per city",
        primary_key=["city", "timestamp"],
        event_time="timestamp",
        online_enabled=True,
        time_travel_format="HUDI",
    )
    fg.insert(df)
    print(f"Backfilled {len(df)} row(s) into '{FEATURE_GROUP_NAME}' (v{FEATURE_GROUP_VERSION})")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    _require_env()

    end_date = date.today() - timedelta(days=1)  # archive data usually lags ~1 day
    start_date = end_date - timedelta(days=365 * BACKFILL_YEARS)

    print(f"Fetching {BACKFILL_YEARS} year(s) of history for {CITY_NAME}: {start_date} to {end_date}")
    print(f"Target feature group: '{FEATURE_GROUP_NAME}' (v{FEATURE_GROUP_VERSION})")

    weather_df = fetch_historical_weather(CITY_LAT, CITY_LON, start_date, end_date)
    print(f"Fetched {len(weather_df)} hourly weather rows")

    pollution_df = fetch_historical_pollution(CITY_LAT, CITY_LON, start_date, end_date)
    print(f"Fetched {len(pollution_df)} hourly pollution rows")

    df = build_backfill_dataframe(weather_df, pollution_df)
    print(f"Built {len(df)} feature rows after merge + feature engineering")
    print(df.dtypes)
    print(df.head())
    print(df.tail())

    push_to_hopsworks(df)


if __name__ == "__main__":
    main()