# Pearls AQI Predictor

Pearls AQI Predictor is an end-to-end machine learning web application designed to predict the Air Quality Index (AQI) for Lahore, Pakistan, up to three days in advance. The system combines automated data collection, feature engineering, machine learning models, Hopsworks Feature Store, model explainability with SHAP, and a React-based dashboard.

The project uses Open-Meteo for weather and air-quality data, Hopsworks for feature storage and model management, FastAPI for the backend API, and React with Vite and Tailwind CSS for the frontend. The frontend is deployed on Vercel and the backend is deployed on FastAPI Cloud. :contentReference[oaicite:1]{index=1}

**Live Project:**  
https://aqi-predictor-green.vercel.app/

## Features

- Current AQI monitoring with AQI category and health guidance.
- 24-hour AQI trend visualization.
- Weather information including temperature, humidity, pressure, and wind speed.
- Pollutant information including PM2.5, PM10, O₃, NO₂, SO₂, and CO.
- AI-powered AQI forecasting for 24, 48, and 72 hours.
- Predicted AQI trend visualization.
- Machine learning models using Ridge, Random Forest, and XGBoost.
- Separate prediction models for day+1, day+2, and day+3.
- Automatic selection of the best-performing model for each forecast horizon.
- SHAP-based explainability showing why a prediction is higher or lower.
- Responsive React dashboard for desktop and mobile devices.
- Live data refresh through the FastAPI backend.
- Secure backend architecture that keeps Hopsworks credentials away from the frontend. 

## How it works

The system follows an automated data-to-prediction pipeline:


             ┌────────────────────┐
             │     Open-Meteo     │
             │ Weather + AQ Data  │
             └─────────┬──────────┘
                       │
                       ▼
             ┌────────────────────┐
             │ Feature Pipeline   │
             │ Data + Engineering │
             └─────────┬──────────┘
                       │
                       ▼
             ┌────────────────────┐
             │ Hopsworks Feature  │
             │       Store        │
             └─────────┬──────────┘
                       │
                       ▼
             ┌────────────────────┐
             │ Training Pipeline  │
             │ Ridge / RF / XGB   │
             └─────────┬──────────┘
                       │
                       ▼
             ┌────────────────────┐
             │ Hopsworks Model    │
             │      Registry      │
             └─────────┬──────────┘
                       │
                       ▼
             ┌────────────────────┐
             │    FastAPI API     │
             │    Backend         │
             └─────────┬──────────┘
                       │ JSON
                       ▼
             ┌────────────────────┐
             │   React Dashboard  │
             │      (Vercel)      │
             └────────────────────┘


## Project Structure


AQI_PREDICTOR/
│
├── .github/
│   └── workflows/
│       ├── feature_pipeline.yml
│       └── training_pipeline.yml
│
├── .vscode/
│
├── backend/
│   ├── __pycache__/
│   ├── .hopsworks_cache/
│   ├── .python-version
│   ├── main.py
│   ├── pyproject.toml
│   └── requirements.txt
│
├── backfill/
│   └── backfill.py
│
├── feature_pipeline/
│   ├── __pycache__/
│   └── feature_pipeline.py
│
├── frontend/
│   ├── dist/
│   ├── node_modules/
│   ├── src/
│   │   ├── components/
│   │   │   ├── AqiGauge.jsx
│   │   │   ├── Common.jsx
│   │   │   ├── CurrentAqiPanel.jsx
│   │   │   ├── Forecast.jsx
│   │   │   ├── Header.jsx
│   │   │   ├── Sidebar.jsx
│   │   │   ├── Skeleton.jsx
│   │   │   ├── TrendChart.jsx
│   │   │   └── WhyPrediction.jsx
│   │   │
│   │   ├── lib/
│   │   │   ├── api.js
│   │   │   ├── aqiColor.js
│   │   │   └── ThemeContext.jsx
│   │   │
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── main.jsx
│   │
│   ├── public/
│   │   └── favicon.svg
│   │
│   ├── index.html
│   ├── package-lock.json
│   ├── package.json
│   ├── postcss.config.js
│   ├── tailwind.config.js
│   └── vite.config.js
│
├── notebooks/
│
├── training_pipeline/
│
├── .env
├── .gitignore
├── LICENSE
├── README.md
└── requirements.txt


## Automation

GitHub Actions automates the main data collection and machine learning pipelines.

| Pipeline | Schedule | Description |
|---|---|---|
| **Feature Pipeline** | Every hour | Collects the latest weather and air-quality data, performs feature engineering, calculates and stores AQI information, and updates the Hopsworks Feature Store. |
| **Training Pipeline** | Every day | Retrieves the latest feature data, trains the forecasting models, evaluates their performance, and registers the best models in Hopsworks. |
| **AQI Forecasting** | Continuous | Uses separate machine learning models to generate **24-hour, 48-hour, and 72-hour** AQI forecasts. |


## License

MIT — see [LICENSE](LICENSE).