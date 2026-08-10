"""
streamlit_app.py

Web dashboard for the AQI Predictor project. Shows:
  1. Current AQI (gauge)
  2. Current pollutants
  3. 24-hour AQI trend
  4. Current conditions (temperature, humidity, pressure, wind speed)
  5. AI AQI forecast (24h / 48h / 72h) using the 3 registered models
  6. Predicted AQI trend graph (today -> +3 days)

Run with:
  streamlit run app/streamlit_app.py

Env vars required (same .env as the other scripts):
  HOPSWORKS_API_KEY    -> from Hopsworks Account Settings -> API keys
  HOPSWORKS_PROJECT    -> your Hopsworks project name
  CITY_NAME            -> e.g. "Lahore"
"""

import os
import shutil
import tempfile

import joblib
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

HOPSWORKS_API_KEY = os.getenv("HOPSWORKS_API_KEY")
HOPSWORKS_PROJECT = os.getenv("HOPSWORKS_PROJECT")
CITY_NAME = os.getenv("CITY_NAME", "Lahore")

FEATURE_GROUP_NAME = "aqi_features"
FEATURE_GROUP_VERSION = 1
HORIZONS = [1, 2, 3]

st.set_page_config(page_title="AQI Predictor", page_icon="🍃", layout="wide")


# ---------------------------------------------------------------------------
# AQI CATEGORY HELPER (standard US EPA bands)
# ---------------------------------------------------------------------------

def aqi_category(aqi: float):
    """Returns (label, color_hex, guidance) for a given AQI value."""
    if aqi <= 50:
        return "Good", "#2ecc71", "Air quality is satisfactory, poses little or no risk."
    elif aqi <= 100:
        return "Moderate", "#f1c40f", "Acceptable; unusually sensitive people should consider limiting prolonged exertion."
    elif aqi <= 150:
        return "Unhealthy for Sensitive Groups", "#e67e22", "Sensitive groups may experience health effects."
    elif aqi <= 200:
        return "Unhealthy", "#e74c3c", "Everyone may begin to experience health effects; sensitive groups may experience more serious effects."
    elif aqi <= 300:
        return "Very Unhealthy", "#8e44ad", "Health alert: everyone may experience more serious health effects."
    else:
        return "Hazardous", "#7f1d1d", "Health warning of emergency conditions; the entire population is more likely to be affected."


# ---------------------------------------------------------------------------
# DATA FETCHING (cached so the app doesn't hit Hopsworks on every rerun)
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False, ttl=1800)
def get_connection():
    import hopsworks

    project = hopsworks.login(project=HOPSWORKS_PROJECT, api_key_value=HOPSWORKS_API_KEY)
    fs = project.get_feature_store()
    mr = project.get_model_registry()
    return project, fs, mr


@st.cache_data(ttl=600, show_spinner="Fetching latest air quality data...")
def fetch_hourly_dataset(_fs) -> pd.DataFrame:
    try:
        fg = _fs.get_feature_group(FEATURE_GROUP_NAME, version=FEATURE_GROUP_VERSION)
        df = fg.read()
    except Exception:
        # The underlying Hopsworks connection can go stale after a period of
        # inactivity (idle gRPC connection timing out) -- if the read fails,
        # drop the cached connection and reconnect fresh once before giving up.
        st.cache_resource.clear()
        _, fs_fresh, _ = get_connection()
        fg = fs_fresh.get_feature_group(FEATURE_GROUP_NAME, version=FEATURE_GROUP_VERSION)
        df = fg.read()

    df = df[df["city"] == CITY_NAME].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
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

    df = pd.get_dummies(df, columns=["day_of_week"], prefix="dow")
    exclude = {"date", "aqi"}
    feature_cols = [c for c in df.columns if c not in exclude]

    latest_row = df.iloc[[-1]]
    reference_date = latest_row["date"].iloc[0]
    X_today = latest_row[feature_cols].copy()
    return X_today, reference_date


# ---------------------------------------------------------------------------
# MODEL LOADING + FORECASTING (cached per model name+version)
# ---------------------------------------------------------------------------

def get_latest_model_version(mr, model_name: str):
    models = mr.get_models(name=model_name)
    if not models:
        return None
    return max(models, key=lambda m: m.version)


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


@st.cache_resource(show_spinner=False)
def load_model_by_version(_mr, model_name: str, version: int):
    hw_model = _mr.get_model(name=model_name, version=version)
    try:
        download_dir = hw_model.download()
        model = _load_model_from_dir(download_dir)
    except Exception:
        # Safety net: a previously-cached local download can still become
        # corrupted (e.g. an interrupted download during a network hiccup).
        # If loading fails, clear the cache and retry once with a fresh
        # download before giving up.
        st.warning(f"Cached model file for '{model_name}' v{version} looked corrupted -- re-downloading...")
        try:
            hw_model.clear_cache()
        except Exception:
            pass
        download_dir = hw_model.download()
        model = _load_model_from_dir(download_dir)

    return model, hw_model.training_metrics


def predict_horizon(model, X_today: pd.DataFrame) -> float:
    X = X_today.copy()
    expected_cols = getattr(model, "feature_names_in_", None)
    if expected_cols is not None:
        X = X.reindex(columns=list(expected_cols), fill_value=0)
    return float(model.predict(X)[0])


@st.cache_data(ttl=600, show_spinner="Generating forecast...")
def get_forecast(_mr, _X_today, _reference_date):
    results = []
    for horizon in HORIZONS:
        model_name = f"aqi_model_day{horizon}"
        latest = get_latest_model_version(_mr, model_name)
        if latest is None:
            continue
        model, metrics = load_model_by_version(_mr, model_name, latest.version)
        prediction = predict_horizon(model, _X_today)
        rmse = float(metrics.get("rmse", float("nan"))) if metrics else float("nan")
        target_date = _reference_date + pd.Timedelta(days=horizon)
        results.append({
            "horizon": horizon, "date": target_date,
            "prediction": prediction, "rmse": rmse,
        })
    return results


# ---------------------------------------------------------------------------
# CHART BUILDERS
# ---------------------------------------------------------------------------

def gauge_chart(aqi: float, color: str) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=aqi,
        number={"suffix": "", "font": {"size": 48, "color": color}},
        gauge={
            "axis": {"range": [0, 300], "visible": False},
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
        },
    ))
    fig.update_layout(height=260, margin=dict(l=20, r=20, t=20, b=0))
    return fig


def trend_chart_24h(hourly_df: pd.DataFrame) -> go.Figure:
    recent = hourly_df.tail(24)
    fig = go.Figure(go.Scatter(
        x=recent["timestamp"], y=recent["aqi"],
        mode="lines", fill="tozeroy",
        line=dict(color="#e74c3c", width=3),
        fillcolor="rgba(231,76,60,0.15)",
    ))
    fig.update_layout(
        height=300, margin=dict(l=20, r=20, t=20, b=20),
        xaxis_title=None, yaxis_title="AQI",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def predicted_trend_chart(current_aqi: float, forecast: list) -> go.Figure:
    x_labels = ["Today"] + [f"+{h['horizon']}d" for h in forecast]
    y_values = [current_aqi] + [h["prediction"] for h in forecast]

    trend_color = "#2ecc71" if y_values[-1] <= y_values[0] else "#e74c3c"

    fig = go.Figure(go.Scatter(
        x=x_labels, y=y_values,
        mode="lines+markers",
        line=dict(color=trend_color, width=3),
        marker=dict(size=10, color=trend_color),
    ))
    fig.update_layout(
        height=300, margin=dict(l=20, r=20, t=20, b=20),
        yaxis_title="AQI", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig, trend_color


# ---------------------------------------------------------------------------
# MAIN APP LAYOUT
# ---------------------------------------------------------------------------

def main():
    st.markdown(
        "<h1 style='margin-bottom:0'>🍃 AQI Predictor</h1>"
        "<p style='color:gray;margin-top:0'>AI-powered air quality intelligence</p>",
        unsafe_allow_html=True,
    )

    col_refresh = st.columns([6, 1])[1]
    if col_refresh.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

    if not HOPSWORKS_API_KEY or not HOPSWORKS_PROJECT:
        st.error("Missing HOPSWORKS_API_KEY / HOPSWORKS_PROJECT. Check your .env file.")
        return

    project, fs, mr = get_connection()
    hourly_df = fetch_hourly_dataset(fs)

    if hourly_df.empty:
        st.warning("No data found yet for this city.")
        return

    latest = hourly_df.iloc[-1]
    current_aqi = float(latest["aqi"])
    label, color, guidance = aqi_category(current_aqi)
    aqi_change = float(latest.get("aqi_change", 0.0))

    # --- 1. CURRENT AQI ---------------------------------------------------
    st.markdown(f"📍 **{CITY_NAME.upper()}**")
    st.subheader("Current Air Quality")
    st.markdown(f"<p style='color:{color};font-size:18px'>{label}</p>", unsafe_allow_html=True)

    c1, c2 = st.columns([1, 2])
    with c1:
        arrow = "↑" if aqi_change > 0 else ("↓" if aqi_change < 0 else "→")
        st.metric("Change vs previous reading", f"{aqi_change:+.0f} points", delta=f"{arrow}")
        st.caption(f"Updated: {latest['timestamp'].strftime('%Y-%m-%d %H:%M')}")
    with c2:
        st.plotly_chart(gauge_chart(current_aqi, color), width='stretch')

    with st.container(border=True):
        st.markdown(f"⚠️ **Air Quality Alert** &nbsp; :{'red' if current_aqi > 100 else 'orange'}[{label}]")
        st.write(guidance)

    st.divider()

    # --- 2. CURRENT POLLUTANTS ---------------------------------------------
    st.subheader("Current Pollutants")
    st.caption(f"Live pollutant concentrations at {CITY_NAME}")
    pollutants = [
        ("PM2.5", latest.get("pm25"), "µg/m³"),
        ("PM10", latest.get("pm10"), "µg/m³"),
        ("O₃", latest.get("o3"), "µg/m³"),
        ("NO₂", latest.get("no2"), "µg/m³"),
        ("SO₂", latest.get("so2"), "µg/m³"),
        ("CO", latest.get("co"), "µg/m³"),
    ]
    cols = st.columns(6)
    for col, (name, value, unit) in zip(cols, pollutants):
        with col:
            with st.container(border=True):
                st.metric(name, f"{value:.1f}" if pd.notna(value) else "N/A")
                st.caption(unit)

    st.divider()

    # --- 3. 24-HOUR AQI TREND ----------------------------------------------
    st.subheader("24-Hour AQI Trend")
    st.caption("Air quality changes over the last 24 hours")
    recent_24h = hourly_df.tail(24)["aqi"]

    stat_cols = st.columns(4)
    stat_cols[0].metric("Current", f"{current_aqi:.0f}")
    stat_cols[1].metric("Avg", f"{recent_24h.mean():.0f}")
    stat_cols[2].metric("Min", f"{recent_24h.min():.0f}")
    stat_cols[3].metric("Max", f"{recent_24h.max():.0f}")

    st.plotly_chart(trend_chart_24h(hourly_df), width='stretch')

    st.divider()

    # --- 4. CURRENT CONDITIONS ---------------------------------------------
    st.subheader("Current Conditions")
    st.caption("Weather variables at time of measurement")
    cond_cols = st.columns(4)
    cond_cols[0].metric("🌡️ Temperature", f"{latest.get('temperature', float('nan')):.1f}°C")
    cond_cols[1].metric("💧 Humidity", f"{latest.get('humidity', float('nan')):.0f}%")
    cond_cols[2].metric("📊 Pressure", f"{latest.get('pressure', float('nan')):.1f} hPa")
    cond_cols[3].metric("💨 Wind Speed", f"{latest.get('wind_speed', float('nan')):.1f} m/s")

    st.divider()

    # --- 5. AI AQI FORECAST --------------------------------------------------
    st.subheader("AI Air Quality Forecast")
    st.caption("Predicted AQI for the next three days")

    daily = build_daily_dataset(hourly_df)
    X_today, reference_date = build_latest_feature_row(daily)

    if X_today is None:
        st.info("Not enough historical data yet to generate a forecast (need ~14+ days).")
    else:
        forecast = get_forecast(mr, X_today, reference_date)

        if not forecast:
            st.warning("No trained models found in the Model Registry yet.")
        else:
            f_cols = st.columns(len(forecast))
            for col, h in zip(f_cols, forecast):
                f_label, f_color, _ = aqi_category(h["prediction"])
                with col:
                    with st.container(border=True):
                        st.caption(f"{h['horizon']*24}h — Day {h['horizon']}")
                        st.markdown(f"<span style='color:{f_color};font-size:14px'>{f_label}</span>", unsafe_allow_html=True)
                        st.markdown(f"<span style='font-size:32px;font-weight:bold;color:{f_color}'>{h['prediction']:.1f}</span> predicted AQI", unsafe_allow_html=True)
                        st.caption(f"Model RMSE: ±{h['rmse']:.2f}" if pd.notna(h["rmse"]) else "Model RMSE: N/A")

            st.divider()

            # --- 6. PREDICTED AQI TREND GRAPH -----------------------------
            st.subheader("Predicted AQI Trend")
            st.caption("Today through 72-hour AI forecast")

            fig, trend_color = predicted_trend_chart(current_aqi, forecast)
            trend_word = "Expected to improve" if trend_color == "#2ecc71" else "Expected to worsen"
            st.markdown(f"<p style='color:{trend_color};text-align:right'>{trend_word}</p>", unsafe_allow_html=True)
            st.plotly_chart(fig, width='stretch')

    st.divider()
    st.caption(f"AQI Predictor · Air-quality intelligence for {CITY_NAME}")


if __name__ == "__main__":
    main()