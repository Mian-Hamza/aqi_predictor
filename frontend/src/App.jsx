import { useCallback, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Atom, Cloud, Sun, Car, Factory, Flame, Thermometer, Droplet, Gauge, Wind } from "lucide-react";
import { api } from "./lib/api.js";
import Header from "./components/Header.jsx";
import CurrentAqiPanel from "./components/CurrentAqiPanel.jsx";
import { Section, StatCard } from "./components/Common.jsx";
import TrendChart, { TREND_RANGES } from "./components/TrendChart.jsx";
import { ForecastCards, PredictedTrendChart } from "./components/Forecast.jsx";
import WhyPrediction from "./components/WhyPrediction.jsx";

const POLLUTANT_META = [
  { key: "pm25", label: "PM2.5", icon: Atom },
  { key: "pm10", label: "PM10", icon: Cloud },
  { key: "o3", label: "O₃", icon: Sun },
  { key: "no2", label: "NO₂", icon: Car },
  { key: "so2", label: "SO₂", icon: Factory },
  { key: "co", label: "CO", icon: Flame },
];

const CONDITION_META = [
  { key: "temperature", label: "Temperature", icon: Thermometer, unit: "°C" },
  { key: "humidity", label: "Humidity", icon: Droplet, unit: "%" },
  { key: "pressure", label: "Pressure", icon: Gauge, unit: "hPa" },
  { key: "wind_speed", label: "Wind Speed", icon: Wind, unit: "m/s" },
];

export default function App() {
  const [current, setCurrent] = useState(null);
  const [trend, setTrend] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [trendHours, setTrendHours] = useState(TREND_RANGES[0]); // 24
  const [trendLoading, setTrendLoading] = useState(false);

  const loadAll = useCallback(async () => {
    setError(null);
    try {
      const [currentRes, trendRes] = await Promise.all([api.current(), api.trend(trendHours)]);
      setCurrent(currentRes);
      setTrend(trendRes);

      try {
        const forecastRes = await api.forecast();
        setForecast(forecastRes);
      } catch (forecastErr) {
        setForecast(null); // forecast can legitimately be unavailable early on
      }
    } catch (err) {
      setError(err.message || "Something went wrong fetching data.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [trendHours]);

  const handleTrendHoursChange = useCallback((hours) => {
    setTrendHours(hours);
    setTrendLoading(true);
    api
      .trend(hours)
      .then(setTrend)
      .catch((err) => setError(err.message || "Failed to load trend."))
      .finally(() => setTrendLoading(false));
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleRefresh = () => {
    setRefreshing(true);
    loadAll();
  };

  const cityName = current?.city || import.meta.env.VITE_CITY_NAME || "City";

  return (
    <div className="min-h-screen bg-canvas">
      <div className="max-w-5xl mx-auto px-4 md:px-6 py-6 md:py-10">
        <Header
          city={cityName}
          color={current?.color}
          updatedAt={current?.timestamp}
          onRefresh={handleRefresh}
          refreshing={refreshing}
        />

        <AnimatePresence mode="wait">
          {loading && (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-center py-24 text-muted"
            >
              Loading air quality data…
            </motion.div>
          )}

          {!loading && error && (
            <motion.div
              key="error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="bg-red-50 border border-red-200 text-red-700 rounded-card p-6 text-sm"
            >
              <p className="font-semibold mb-1">Couldn't load data</p>
              <p>{error}</p>
              <p className="text-xs text-red-500 mt-2">
                Make sure the backend is running at the configured API URL.
              </p>
            </motion.div>
          )}

          {!loading && !error && current && (
            <motion.div key="content" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <Section title="">
                <CurrentAqiPanel current={current} />
              </Section>

              <Section title="Current Pollutants" caption={`Live pollutant concentrations at ${cityName}`}>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
                  {POLLUTANT_META.map((p, i) => (
                    <StatCard
                      key={p.key}
                      icon={p.icon}
                      label={p.label}
                      value={current.pollutants[p.key]}
                      unit="µg/m³"
                      index={i}
                    />
                  ))}
                </div>
              </Section>

              {trend && (
                <Section
                  title={`${trendHours}-Hour AQI Trend`}
                  caption={`Air quality changes over the last ${trendHours} hours`}
                >
                  <TrendChart
                    trend={trend}
                    color={current.color}
                    hours={trendHours}
                    onHoursChange={handleTrendHoursChange}
                    loading={trendLoading}
                  />
                </Section>
              )}

              <Section title="Current Conditions" caption="Weather variables at time of measurement">
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                  {CONDITION_META.map((c, i) => (
                    <StatCard
                      key={c.key}
                      icon={c.icon}
                      label={c.label}
                      value={current.conditions[c.key]}
                      unit={c.unit}
                      index={i}
                    />
                  ))}
                </div>
              </Section>

              {forecast ? (
                <>
                  <Section title="AI Air Quality Forecast" caption="Predicted AQI for the next three days">
                    <ForecastCards forecast={forecast} />
                  </Section>

                  <Section title="Predicted AQI Trend" caption="Today through 72-hour AI forecast">
                    <PredictedTrendChart forecast={forecast} />
                  </Section>

                  <Section title="">
                    <WhyPrediction />
                  </Section>
                </>
              ) : (
                <Section title="AI Air Quality Forecast">
                  <div className="bg-surface border border-border rounded-card p-6 text-sm text-muted">
                    Not enough historical data yet to generate a forecast, or no trained models are
                    registered yet.
                  </div>
                </Section>
              )}

              <p className="text-center text-xs text-muted mt-10">
               Pearls AQI Predictor · Air-quality intelligence for {cityName}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}