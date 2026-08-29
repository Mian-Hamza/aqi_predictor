import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Cell, LabelList } from "recharts";
import { Activity, TrendingUp, TrendingDown, ChevronDown, ChevronUp } from "lucide-react";
import { Card } from "./Common.jsx";
import { api } from "../lib/api.js";
import { useTheme } from "../lib/ThemeContext.jsx";

const INCREASE_COLOR = "#F43F5E"; // rose -- makes prediction higher
const DECREASE_COLOR = "#14B8A6"; // teal -- makes prediction lower
const TOP_N = 8; // how many features to show before "Show all" is needed

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
    <div className="bg-white dark:bg-surface border border-border rounded-lg px-3 py-2 shadow-lg">
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

// Custom label renderer so the value prints just outside the bar's outer
// edge, flipping side automatically based on the bar's sign -- recharts'
// built-in LabelList position="right" doesn't handle diverging
// positive/negative bars around a center 0 line on its own.
//
// IMPORTANT: for negative bars, Recharts reports `x` as the CENTER/zero
// line (not the bar's left edge) and `width` as a NEGATIVE number
// extending leftward -- not the left-edge+positive-width shape you'd
// assume from the positive-bar case. Using `x - 6` directly therefore
// landed the label just inside the zero line, i.e. ON TOP of the teal
// bar itself (invisible for large bars since the label's teal text color
// matched the teal bar fill; barely visible as a sliver for small ones).
// Math.min/max normalizes this regardless of which convention Recharts
// hands back, so the label always lands truly outside the bar.
function ValueLabel(isDark) {
  return function renderLabel(props) {
    const { x, y, width, height, value } = props;
    const isIncrease = value >= 0;
    const leftEdge = Math.min(x, x + width);
    const rightEdge = Math.max(x, x + width);
    const labelX = isIncrease ? rightEdge + 6 : leftEdge - 6;
    const color = isIncrease ? INCREASE_COLOR : DECREASE_COLOR;

    return (
      <text
        x={labelX}
        y={y + height / 2}
        dy={4}
        textAnchor={isIncrease ? "start" : "end"}
        fontSize={11}
        fontWeight={600}
        fill={color}
      >
        {isIncrease ? "+" : ""}
        {value}
      </text>
    );
  };
}

export default function WhyPrediction() {
  const { isDark } = useTheme();
  const tickColor = isDark ? "#94A3B8" : "#667085";
  const yTickColor = isDark ? "#CBD5E1" : "#475467";
  const referenceLineStroke = isDark ? "#334155" : "#D0D5DD";
  const cursorFill = isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.03)";

  const [horizon, setHorizon] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setShowAll(false); // reset when switching horizon tabs

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

  // Sorted by magnitude of impact (biggest driver first) -- reads as a
  // ranked list rather than the harder-to-parse SHAP-convention ordering.
  const sortedData = [...(data?.contributions || [])].sort(
    (a, b) => Math.abs(b.shap_value) - Math.abs(a.shap_value)
  );
  const hasMore = sortedData.length > TOP_N;
  const chartData = showAll ? sortedData : sortedData.slice(0, TOP_N);
  const hiddenCount = sortedData.length - TOP_N;

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
                  ? "bg-white dark:bg-surface text-ink shadow-sm"
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

            <AnimatePresence mode="wait">
              <motion.div
                key={showAll ? "all" : "top"}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.25 }}
              >
                <ResponsiveContainer width="100%" height={Math.max(280, chartData.length * 34)}>
                  <BarChart
                    data={chartData}
                    layout="vertical"
                    margin={{ top: 4, right: 44, left: 4, bottom: 4 }}
                    barCategoryGap={10}
                  >
                    <XAxis
                      type="number"
                      domain={[-maxAbs * 1.25, maxAbs * 1.25]}
                      tick={{ fontSize: 11, fill: tickColor }}
                      axisLine={false}
                      tickLine={false}
                      allowDecimals={false}
                      tickFormatter={(v) => Math.round(v)}
                    />
                    <YAxis
                      type="category"
                      dataKey="feature"
                      width={150}
                      tick={{ fontSize: 11.5, fill: yTickColor, fontWeight: 500 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <ReferenceLine x={0} stroke={referenceLineStroke} />
                    <Tooltip content={<CustomTooltip />} cursor={{ fill: cursorFill }} />
                    <Bar dataKey="shap_value" radius={5} animationDuration={500} barSize={18}>
                      {chartData.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={entry.shap_value >= 0 ? INCREASE_COLOR : DECREASE_COLOR}
                        />
                      ))}
                      <LabelList dataKey="shap_value" content={ValueLabel(isDark)} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </motion.div>
            </AnimatePresence>

            {hasMore && (
              <button
                onClick={() => setShowAll((v) => !v)}
                className="mt-3 flex items-center gap-1.5 mx-auto text-xs font-semibold text-accent hover:opacity-75 transition-opacity"
              >
                {showAll ? (
                  <>
                    Show top {TOP_N} only <ChevronUp size={14} />
                  </>
                ) : (
                  <>
                    Show all {sortedData.length} features ({hiddenCount} more) <ChevronDown size={14} />
                  </>
                )}
              </button>
            )}

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