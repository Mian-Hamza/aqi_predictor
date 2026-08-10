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
    """Returns (label, color_hex, guidance) using the dashboard's four AQI bands."""
    if aqi <= 50:
        return "Low", "#3498db", "Air quality is good and generally poses little or no risk."
    elif aqi <= 100:
        return "Medium", "#2ecc71", "Air quality is acceptable for most people."
    elif aqi <= 150:
        return "Above Medium", "#f1c40f", "Air quality is elevated; sensitive people should consider reducing prolonged outdoor activity."
    else:
        return "High", "#e74c3c", "Air quality is high; consider limiting prolonged outdoor exposure, especially if sensitive."


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
    # Four dashboard bands:
    # Low = blue, Medium = green, Above Medium = yellow, High = red.
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=aqi,
        number={
            "suffix": "",
            "font": {"size": 54, "color": color, "family": "Arial Black"}
        },
        gauge={
            "axis": {
                "range": [0, 300],
                "tickmode": "array",
                "tickvals": [0, 50, 100, 150, 200, 300],
                "ticktext": ["0", "50", "100", "150", "200", "300"],
                "tickfont": {"size": 10, "color": "#64748b"},
            },
            "bar": {"color": color, "thickness": 0.30},
            "steps": [
                {"range": [0, 50], "color": "#3498db"},
                {"range": [50, 100], "color": "#2ecc71"},
                {"range": [100, 150], "color": "#f1c40f"},
                {"range": [150, 300], "color": "#e74c3c"},
            ],
            "threshold": {
                "line": {"color": color, "width": 5},
                "thickness": 0.85,
                "value": aqi,
            },
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
        },
    ))
    fig.update_layout(
        height=285,
        margin=dict(l=20, r=20, t=18, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, Arial, sans-serif"},
    )
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
# MAIN APP LAYOUT / STYLING
# ---------------------------------------------------------------------------

def apply_custom_css():
    st.markdown(
        """
        <style>
        /* Overall page */
        .stApp {
            background:
                radial-gradient(circle at 10% 0%, rgba(52,152,219,0.08), transparent 28%),
                radial-gradient(circle at 95% 10%, rgba(46,204,113,0.08), transparent 28%),
                #f7f9fc;
        }

        .block-container {
            max-width: 1450px;
            padding-top: 2rem;
            padding-bottom: 2rem;
        }

        /* Header */
        .aqi-header {
            background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 55%, #166534 100%);
            border-radius: 22px;
            padding: 28px 32px;
            margin-bottom: 22px;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.12);
        }

        .aqi-header h1 {
            color: white;
            margin: 0;
            font-size: 2.35rem;
            letter-spacing: -0.8px;
        }

        .aqi-header p {
            color: rgba(255,255,255,0.78);
            margin: 7px 0 0 0;
            font-size: 1rem;
        }

        .location-pill {
            display: inline-block;
            margin-top: 16px;
            padding: 7px 13px;
            border-radius: 999px;
            background: rgba(255,255,255,0.13);
            color: white;
            font-size: 0.82rem;
            font-weight: 600;
        }

        /* Section headings */
        .section-title {
            font-size: 1.35rem;
            font-weight: 750;
            color: #0f172a;
            margin: 4px 0 2px 0;
        }

        .section-subtitle {
            color: #64748b;
            margin: 0 0 15px 0;
            font-size: 0.9rem;
        }

        /* AQI hero card */
        .aqi-hero {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 20px;
            padding: 20px 24px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
        }

        .aqi-score {
            font-size: 4.2rem;
            font-weight: 800;
            line-height: 1;
            margin: 4px 0 5px 0;
        }

        .aqi-label {
            font-size: 1.05rem;
            font-weight: 700;
            margin-bottom: 13px;
        }

        .aqi-guidance {
            color: #475569;
            font-size: 0.92rem;
            line-height: 1.55;
            background: #f8fafc;
            border-radius: 12px;
            padding: 12px 14px;
            border-left: 4px solid #cbd5e1;
        }

        /* Small stat cards */
        .mini-card {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 16px;
            height: 100%;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.045);
        }

        .mini-card .title {
            color: #64748b;
            font-size: 0.78rem;
            font-weight: 650;
            margin-bottom: 5px;
        }

        .mini-card .value {
            color: #0f172a;
            font-size: 1.55rem;
            font-weight: 780;
        }

        .mini-card .unit {
            color: #94a3b8;
            font-size: 0.75rem;
            margin-top: 3px;
        }

        /* Forecast cards */
        .forecast-card {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 18px;
            padding: 18px;
            min-height: 145px;
            box-shadow: 0 7px 20px rgba(15, 23, 42, 0.05);
        }

        .forecast-day {
            color: #64748b;
            font-size: 0.8rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .forecast-value {
            font-size: 2rem;
            font-weight: 800;
            line-height: 1.1;
            margin: 8px 0 4px 0;
        }

        /* Streamlit controls */
        div.stButton > button {
            border-radius: 11px;
            border: 1px solid #cbd5e1;
            font-weight: 650;
            padding: 0.55rem 1rem;
            transition: all 0.2s ease;
        }

        div.stButton > button:hover {
            border-color: #3498db;
            color: #1d4ed8;
            box-shadow: 0 5px 15px rgba(52,152,219,0.15);
        }

        /* Remove excessive default vertical spacing */
        div[data-testid="stVerticalBlock"] > div:has(> div.stMarkdown) {
            gap: 0.35rem;
        }

        /* Mobile */
        @media (max-width: 900px) {
            .aqi-header h1 { font-size: 1.8rem; }
            .aqi-score { font-size: 3.2rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# MAIN APP LAYOUT
# ---------------------------------------------------------------------------

def main():
    apply_custom_css()

    st.markdown(
        f"""
        <div class="aqi-header">
            <h1>🍃 AQI Predictor</h1>
            <p>AI-powered air quality intelligence and forecasting dashboard</p>
            <span class="location-pill">📍 {CITY_NAME.upper()}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    top_left, top_right = st.columns([8, 1])
    with top_right:
        if st.button("🔄 Refresh", use_container_width=True):
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
    st.markdown('<div class="section-title">Current Air Quality</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Live AQI reading with color-coded air-quality level</div>',
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns([1.05, 1.95], gap="large")

    with c1:
        st.markdown(
            f"""
            <div class="aqi-hero">
                <div class="title" style="color:#64748b;font-size:.85rem;font-weight:650;">
                    CURRENT AQI
                </div>
                <div class="aqi-score" style="color:{color};">{current_aqi:.0f}</div>
                <div class="aqi-label" style="color:{color};">● {label}</div>
                <div class="aqi-guidance" style="border-left-color:{color};">
                    {guidance}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        arrow = "↑" if aqi_change > 0 else ("↓" if aqi_change < 0 else "→")
        delta_color = "#e74c3c" if aqi_change > 0 else ("#2ecc71" if aqi_change < 0 else "#64748b")

        st.markdown(
            f"""
            <div style="display:flex;gap:12px;margin-top:14px;">
                <div class="mini-card" style="flex:1;">
                    <div class="title">CHANGE</div>
                    <div class="value" style="color:{delta_color};">{arrow} {aqi_change:+.0f}</div>
                    <div class="unit">vs previous reading</div>
                </div>
                <div class="mini-card" style="flex:1;">
                    <div class="title">UPDATED</div>
                    <div class="value" style="font-size:1.05rem;">
                        {latest['timestamp'].strftime('%H:%M')}
                    </div>
                    <div class="unit">{latest['timestamp'].strftime('%d %b %Y')}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        st.plotly_chart(
            gauge_chart(current_aqi, color),
            use_container_width=True,
            config={"displayModeBar": False},
        )
        st.markdown(
            """
            <div style="display:flex;justify-content:center;gap:18px;flex-wrap:wrap;
                        margin-top:-8px;color:#64748b;font-size:.78rem;font-weight:650;">
                <span><b style="color:#3498db;">●</b> Low (0–50)</span>
                <span><b style="color:#2ecc71;">●</b> Medium (51–100)</span>
                <span><b style="color:#f1c40f;">●</b> Above Medium (101–150)</span>
                <span><b style="color:#e74c3c;">●</b> High (151+)</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()

    # --- 2. CURRENT POLLUTANTS ---------------------------------------------
    st.markdown('<div class="section-title">Current Pollutants</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="section-subtitle">Live pollutant concentrations at {CITY_NAME}</div>',
        unsafe_allow_html=True,
    )
    pollutants = [
        ("PM2.5", latest.get("pm25"), "µg/m³"),
        ("PM10", latest.get("pm10"), "µg/m³"),
        ("O₃", latest.get("o3"), "µg/m³"),
        ("NO₂", latest.get("no2"), "µg/m³"),
        ("SO₂", latest.get("so2"), "µg/m³"),
        ("CO", latest.get("co"), "µg/m³"),
    ]
    cols = st.columns(6, gap="medium")
    for col, (name, value, unit) in zip(cols, pollutants):
        value_text = f"{value:.1f}" if pd.notna(value) else "N/A"
        with col:
            st.markdown(
                f"""
                <div class="mini-card">
                    <div class="title">{name}</div>
                    <div class="value">{value_text}</div>
                    <div class="unit">{unit}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()

    # --- 3. 24-HOUR AQI TREND ----------------------------------------------
    st.markdown('<div class="section-title">24-Hour AQI Trend</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Air quality changes over the last 24 hours</div>',
        unsafe_allow_html=True,
    )
    recent_24h = hourly_df.tail(24)["aqi"]

    stat_values = [
        ("CURRENT", current_aqi, color),
        ("AVERAGE", recent_24h.mean(), "#3498db"),
        ("MINIMUM", recent_24h.min(), "#2ecc71"),
        ("MAXIMUM", recent_24h.max(), "#e74c3c"),
    ]
    stat_cols = st.columns(4, gap="medium")
    for col, (name, value, stat_color) in zip(stat_cols, stat_values):
        with col:
            st.markdown(
                f"""
                <div class="mini-card">
                    <div class="title">{name}</div>
                    <div class="value" style="color:{stat_color};">{value:.0f}</div>
                    <div class="unit">AQI points</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.plotly_chart(
        trend_chart_24h(hourly_df),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    st.divider()

    # --- 4. CURRENT CONDITIONS ---------------------------------------------
    st.markdown('<div class="section-title">Current Conditions</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Weather variables at the time of measurement</div>',
        unsafe_allow_html=True,
    )
    conditions = [
        ("🌡️ Temperature", latest.get("temperature", float("nan")), "°C", ".1f"),
        ("💧 Humidity", latest.get("humidity", float("nan")), "%", ".0f"),
        ("📊 Pressure", latest.get("pressure", float("nan")), "hPa", ".1f"),
        ("💨 Wind Speed", latest.get("wind_speed", float("nan")), "m/s", ".1f"),
    ]
    cond_cols = st.columns(4, gap="medium")
    for col, (name, value, unit, fmt) in zip(cond_cols, conditions):
        value_text = "N/A" if pd.isna(value) else format(value, fmt)
        with col:
            st.markdown(
                f"""
                <div class="mini-card">
                    <div class="title">{name}</div>
                    <div class="value">{value_text}</div>
                    <div class="unit">{unit}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

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
            f_cols = st.columns(len(forecast), gap="medium")
            for col, h in zip(f_cols, forecast):
                f_label, f_color, _ = aqi_category(h["prediction"])
                with col:
                    rmse_text = (
                        f"Model RMSE: ±{h['rmse']:.2f}"
                        if pd.notna(h["rmse"])
                        else "Model RMSE: N/A"
                    )
                    st.markdown(
                        f"""
                        <div class="forecast-card">
                            <div class="forecast-day">{h['horizon']*24}h · Day {h['horizon']}</div>
                            <div style="color:{f_color};font-weight:700;font-size:.85rem;margin-top:8px;">
                                ● {f_label}
                            </div>
                            <div class="forecast-value" style="color:{f_color};">
                                {h['prediction']:.1f}
                            </div>
                            <div style="color:#64748b;font-size:.78rem;">predicted AQI</div>
                            <div style="color:#94a3b8;font-size:.72rem;margin-top:10px;">{rmse_text}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            st.divider()

            # --- 6. PREDICTED AQI TREND GRAPH -----------------------------
            st.markdown('<div class="section-title">Predicted AQI Trend</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="section-subtitle">Today through the 72-hour AI forecast</div>',
                unsafe_allow_html=True,
            )

            fig, trend_color = predicted_trend_chart(current_aqi, forecast)
            trend_word = "Expected to improve" if trend_color == "#2ecc71" else "Expected to worsen"
            st.markdown(
                f"<p style='color:{trend_color};font-weight:700;text-align:right;margin-bottom:-8px;'>"
                f"{trend_word}</p>",
                unsafe_allow_html=True,
            )
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )

    st.divider()
    st.markdown(
        f"""
        <div style="text-align:center;color:#94a3b8;font-size:.78rem;padding:18px 0 4px;">
            🍃 AQI Predictor · Air-quality intelligence for {CITY_NAME}
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()