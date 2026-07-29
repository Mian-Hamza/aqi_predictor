"""
feature_pipeline.py

Fetches current weather + pollution data for a city, engineers features,
and inserts them into a Hopsworks Feature Group.

Designed to be run:
  - Manually first (to test)
  - Then hourly via GitHub Actions / cron

NOTE: AQICN has been removed as an AQI source. Its "Lahore" station was
returning a stale, unchanging AQI value across runs. Instead, 'aqi' is now
calculated locally from PM2.5/PM10 concentrations using the standard US EPA
breakpoint formula (0-500 scale) -- see calculate_us_aqi() below. This is
far more sensitive to real changes than OpenWeather's own coarse 1-5 'aqi'
category, which is kept in the row as 'ow_aqi_category' for reference only.

Env vars required (put these in a local .env file, and as GitHub Secrets later):
  OPENWEATHER_API_KEY  -> from https://openweathermap.org/api (weather + all pollutants + AQI)
  HOPSWORKS_API_KEY    -> from Hopsworks Account Settings -> API keys
  HOPSWORKS_PROJECT    -> your Hopsworks project name
  CITY_NAME            -> e.g. "Lahore" (used for OpenWeather weather endpoint + tagging rows)
  CITY_COUNTRY         -> e.g. "PK" (ISO country code, used for OpenWeather weather endpoint's q=City,Country)
  CITY_LAT             -> e.g. "31.5497" (used for OpenWeather Air Pollution endpoint)
  CITY_LON             -> e.g. "74.3436" (used for OpenWeather Air Pollution endpoint)
  CITY_TIMEZONE        -> e.g. "Asia/Karachi" (used so hour/day/month features reflect LOCAL time, not UTC)
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
HOPSWORKS_API_KEY = os.getenv("HOPSWORKS_API_KEY")
HOPSWORKS_PROJECT = os.getenv("HOPSWORKS_PROJECT")
CITY_NAME = os.getenv("CITY_NAME", "Lahore")
CITY_COUNTRY = os.getenv("CITY_COUNTRY", "PK")
CITY_LAT = float(os.getenv("CITY_LAT", "31.5497"))
CITY_LON = float(os.getenv("CITY_LON", "74.3436"))
CITY_TIMEZONE = os.getenv("CITY_TIMEZONE", "Asia/Karachi")

FEATURE_GROUP_NAME = "aqi_features"
FEATURE_GROUP_VERSION = 1

REQUIRED_ENV_VARS = (
    "OPENWEATHER_API_KEY",
    "HOPSWORKS_API_KEY",
    "HOPSWORKS_PROJECT",
)


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
# US EPA AQI CALCULATION (from raw pollutant concentrations)
# ---------------------------------------------------------------------------
# OpenWeather's own 'aqi' field is a coarse 1-5 category, which barely moves
# run to run. The standard US EPA AQI (0-500 scale) is computed via linear
# interpolation between published concentration "breakpoints" per pollutant,
# and gives a much more sensitive, continuous value -- better for trend
# features like aqi_change and aqi_Nh_ago.
#
# Breakpoints below are the standard EPA tables, in ug/m3.
# Each tuple: (conc_low, conc_high, aqi_low, aqi_high)

PM25_BREAKPOINTS = [
    (0.0, 12.0, 0, 50),
    (12.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 150.4, 151, 200),
    (150.5, 250.4, 201, 300),
    (250.5, 350.4, 301, 400),
    (350.5, 500.4, 401, 500),
]

PM10_BREAKPOINTS = [
    (0, 54, 0, 50),
    (55, 154, 51, 100),
    (155, 254, 101, 150),
    (255, 354, 151, 200),
    (355, 424, 201, 300),
    (425, 504, 301, 400),
    (505, 604, 401, 500),
]


def _calc_sub_aqi(concentration: float, breakpoints: list) -> float:
    """Linear interpolation of a single pollutant's AQI sub-index."""
    if concentration is None or pd.isna(concentration) or concentration < 0:
        return 0.0

    for conc_low, conc_high, aqi_low, aqi_high in breakpoints:
        if conc_low <= concentration <= conc_high:
            return (
                (aqi_high - aqi_low) / (conc_high - conc_low)
            ) * (concentration - conc_low) + aqi_low

    # Above the highest defined breakpoint -- clamp to the max AQI (500,
    # "Hazardous") rather than erroring out on extreme pollution events.
    return 500.0


def calculate_us_aqi(pm25: float, pm10: float) -> float:
    """
    Overall AQI is the MAX of each pollutant's sub-index, per EPA methodology
    (the worst pollutant determines the reported AQI).
    """
    pm25_aqi = _calc_sub_aqi(pm25, PM25_BREAKPOINTS)
    pm10_aqi = _calc_sub_aqi(pm10, PM10_BREAKPOINTS)
    return round(max(pm25_aqi, pm10_aqi), 1)


# ---------------------------------------------------------------------------
# 1. FETCH RAW DATA
# ---------------------------------------------------------------------------

def fetch_openweather_pollution(lat: float, lon: float) -> dict:
    """
    Fetch AQI + pollutant concentrations from OpenWeather's Air Pollution API.
    'aqi' here is OpenWeather's own 1-5 scale (1=Good ... 5=Very Poor) --
    NOT the US EPA 0-500 scale. Document this clearly in your final report.
    """
    resp = requests.get(
        "https://api.openweathermap.org/data/2.5/air_pollution",
        params={"lat": lat, "lon": lon, "appid": OPENWEATHER_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()

    items = payload.get("list", [])
    if not items:
        raise RuntimeError(f"OpenWeather Air Pollution API returned no data: {payload}")

    entry = items[0]
    components = entry.get("components", {})

    return {
        "ow_aqi_category": entry.get("main", {}).get("aqi"),  # OpenWeather's own 1-5 scale, kept for reference
        "pm25": components.get("pm2_5"),
        "pm10": components.get("pm10"),
        "no2": components.get("no2"),
        "so2": components.get("so2"),
        "o3": components.get("o3"),
        "co": components.get("co"),
    }


def fetch_openweather_weather(city: str, country: str) -> dict:
    """Fetch current weather readings from OpenWeather."""
    resp = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={"q": f"{city},{country}", "appid": OPENWEATHER_API_KEY, "units": "metric"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    return {
        "temperature": data.get("main", {}).get("temp"),
        "feels_like": data.get("main", {}).get("feels_like"),
        "max_temperature": data.get("main", {}).get("temp_max"),
        "min_temperature": data.get("main", {}).get("temp_min"),
        "humidity": data.get("main", {}).get("humidity"),
        "pressure": data.get("main", {}).get("pressure"),
        "wind_speed": data.get("wind", {}).get("speed"),
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
    """
    return {
        "hour": local_ts.hour,
        "day_of_week": local_ts.weekday(),  # 0=Monday ... 6=Sunday
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

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp")

        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
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

    now = pd.Timestamp.now(tz="UTC")

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

    pollution_data = fetch_openweather_pollution(CITY_LAT, CITY_LON)
    weather = fetch_openweather_weather(CITY_NAME, CITY_COUNTRY)
    time_feats = build_time_features(local_now)

    # Our own continuous US EPA AQI (0-500), computed from PM2.5/PM10 -- this
    # is what feeds aqi_change, aqi_1h_ago, etc. OpenWeather's coarse 1-5
    # 'ow_aqi_category' is kept in the row separately, just for reference.
    us_aqi = calculate_us_aqi(
        pm25=_to_float(pollution_data.get("pm25")),
        pm10=_to_float(pollution_data.get("pm10")),
    )
    pollution_data["aqi"] = us_aqi

    current_aqi = us_aqi

    history = get_recent_history(fs, hours=24) if fs is not None else pd.DataFrame()
    lag_feats = compute_lag_features(history, current_aqi=current_aqi)

    row = {
        "city": CITY_NAME,
        "timestamp": utc_now,
        **pollution_data,
        **weather,
        **time_feats,
        **lag_feats,
    }

    df = pd.DataFrame([row])

    numeric_cols = [c for c in df.columns if c not in ("city", "timestamp")]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Force these specific columns to float64 explicitly. Without this, pandas
    # may infer int64 for a row where the value happens to be a whole number,
    # which locks the Hopsworks feature group schema to 'bigint' on first
    # creation -- then a later decimal value fails schema validation.
    float_cols = [
        "aqi", "ow_aqi_category", "pm25", "pm10", "no2", "so2", "o3", "co",
        "temperature", "feels_like", "min_temperature", "max_temperature",
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