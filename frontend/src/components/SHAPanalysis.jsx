import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Cell } from "recharts";
import { Activity, TrendingUp, TrendingDown } from "lucide-react";
import { Card } from "./Common.jsx";
import { api } from "../lib/api.js";

const INCREASE_COLOR = "#F43F5E"; // rose -- makes prediction higher
const DECREASE_COLOR = "#14B8A6"; // teal -- makes prediction lower

const HORIZON_TABS = [
  { horizon: 1, label: "24h" },
  { horizon: 2, label: "48h" },
  { horizon: 3, label: "72h" },
];

function CustomTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  const isIncrease = p.shap_value >= 0;
  const color = isIncrease ? INCREASE_COLOR : DECREASE_COLOR;

  return (
    <div className="bg-white border border-border rounded-lg px-3 py-2 shadow-lg">
      <p className="font-semibold text-sm mb-0.5 text-ink">{p.feature}</p>
      <p className="font-semibold" style={{ color }}>
        {isIncrease ? "+" : ""}
        {p.shap_value} AQI
      </p>
      <p className="text-xs text-muted mt-0.5">
        {isIncrease ? "Makes prediction higher" : "Makes prediction lower"}
      </p>
    </div>
  );
}

export default function WhyPrediction() {
  const [horizon, setHorizon] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .explain(horizon)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [horizon]);

  const chartData = data?.contributions || [];
  const maxAbs = chartData.length
    ? Math.max(...chartData.map((c) => Math.abs(c.shap_value)))
    : 10;

  return (
    <Card>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-5">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-accent/10 flex items-center justify-center text-accent shrink-0">
            <Activity size={18} strokeWidth={2.25} />
          </div>
          <div>
            <h3 className="font-display font-semibold text-ink">Why this prediction</h3>
            <p className="text-xs text-muted">
              SHAP feature contributions for the {horizon * 24}-hour forecast
            </p>
          </div>
        </div>

        <div className="flex bg-canvas border border-border rounded-full p-1 self-start sm:self-auto">
          {HORIZON_TABS.map((t) => (
            <button
              key={t.horizon}
              onClick={() => setHorizon(t.horizon)}
              className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                horizon === t.horizon
                  ? "bg-white text-ink shadow-sm"
                  : "text-muted hover:text-ink"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <AnimatePresence mode="wait">
        {loading && (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="py-16 text-center text-sm text-muted"
          >
            Computing feature contributions…
          </motion.div>
        )}

        {!loading && error && (
          <motion.div
            key="error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="py-10 text-center text-sm text-muted"
          >
            {error.includes("Not enough")
              ? "Not enough historical data yet to compute an explanation."
              : `Couldn't load explanation: ${error}`}
          </motion.div>
        )}

        {!loading && !error && data && (
          <motion.div key={horizon} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
              <div className="bg-canvas rounded-xl p-3">
                <p className="text-xs text-muted mb-1">Predicted AQI</p>
                <p className="font-display text-xl font-bold text-ink">{data.predicted_aqi}</p>
              </div>
              <div className="bg-canvas rounded-xl p-3">
                <p className="text-xs text-muted mb-1 flex items-center gap-1">
                  <TrendingUp size={12} /> Top increase
                </p>
                <p className="text-sm font-semibold text-ink">
                  {data.top_increase
                    ? `${data.top_increase.feature} (+${data.top_increase.shap_value})`
                    : "—"}
                </p>
              </div>
              <div className="bg-canvas rounded-xl p-3">
                <p className="text-xs text-muted mb-1 flex items-center gap-1">
                  <TrendingDown size={12} /> Top decrease
                </p>
                <p className="text-sm font-semibold text-ink">
                  {data.top_decrease
                    ? `${data.top_decrease.feature} (${data.top_decrease.shap_value})`
                    : "—"}
                </p>
              </div>
            </div>

            <ResponsiveContainer width="100%" height={Math.max(320, chartData.length * 24)}>
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ top: 4, right: 24, left: 4, bottom: 4 }}
                barCategoryGap={4}
              >
                <XAxis
                  type="number"
                  domain={[-maxAbs * 1.15, maxAbs * 1.15]}
                  tick={{ fontSize: 11, fill: "#667085" }}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                  tickFormatter={(v) => Math.round(v)}
                />
                <YAxis
                  type="category"
                  dataKey="feature"
                  width={150}
                  tick={{ fontSize: 11, fill: "#475467" }}
                  axisLine={false}
                  tickLine={false}
                />
                <ReferenceLine x={0} stroke="#D0D5DD" />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(0,0,0,0.03)" }} />
                <Bar dataKey="shap_value" radius={3} animationDuration={600}>
                  {chartData.map((entry, i) => (
                    <Cell
                      key={i}
                      fill={entry.shap_value >= 0 ? INCREASE_COLOR : DECREASE_COLOR}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>

            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mt-4 pt-4 border-t border-border text-xs text-muted">
              <div className="flex flex-wrap items-center gap-4">
                <span className="flex items-center gap-1.5">
                  <span
                    className="w-2.5 h-2.5 rounded-sm inline-block"
                    style={{ backgroundColor: INCREASE_COLOR }}
                  />
                  Increases predicted AQI
                </span>
                <span className="flex items-center gap-1.5">
                  <span
                    className="w-2.5 h-2.5 rounded-sm inline-block"
                    style={{ backgroundColor: DECREASE_COLOR }}
                  />
                  Decreases predicted AQI
                </span>
              </div>
              <span>SHAP values measure the contribution of each feature toward the predicted outcome.</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}