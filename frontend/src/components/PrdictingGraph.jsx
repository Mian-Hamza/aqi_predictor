import { motion } from "framer-motion";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Dot } from "recharts";
import { Card, Badge } from "./Common.jsx";

export function ForecastCards({ forecast }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
      {forecast.forecast.map((h, i) => (
        <motion.div
          key={h.horizon}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.08, duration: 0.35 }}
          whileHover={{ y: -3 }}
        >
          <Card>
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-xs text-muted">{h.horizon * 24}h</p>
                <p className="text-sm font-semibold text-ink">Day {h.horizon}</p>
              </div>
              <Badge label={h.category} color={h.color} />
            </div>
            <div className="font-display text-3xl font-bold tabular-nums" style={{ color: h.color }}>
              {h.prediction}
              <span className="text-sm font-medium text-muted ml-1">predicted AQI</span>
            </div>
            {h.rmse != null && (
              <p className="text-xs text-muted mt-3">Model RMSE: ±{h.rmse}</p>
            )}
          </Card>
        </motion.div>
      ))}
    </div>
  );
}

function ActiveDot(props) {
  const { cx, cy, payload } = props;
  return <Dot cx={cx} cy={cy} r={5} fill={payload.color} stroke="#fff" strokeWidth={2} />;
}

// Same fix as TrendChart.jsx: build explicit, evenly-spaced ticks (step of
// 50) from the real data range instead of letting Recharts guess a domain
// via a function, which was producing uneven gaps like 65 / 65 / 120.
function buildYAxisTicks(data) {
  const maxAqi = data.length ? Math.max(...data.map((d) => d.aqi)) : 0;
  const bufferedMax = maxAqi + 20;
  const niceMax = Math.max(150, Math.ceil(bufferedMax / 50) * 50);

  const ticks = [];
  for (let v = 0; v <= niceMax; v += 50) ticks.push(v);

  return { ticks, niceMax };
}

// Custom tooltip: reads `color` straight off the hovered point's own data
// (the same severity color used for that point's dot), so the AQI value
// always renders in that point's color -- not the overall trend line's
// green/red "improving/worsening" color, which is a different concept.
function CustomTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0].payload; // { label, aqi, color }
  return (
    <div
      className="bg-white px-3.5 py-2.5 shadow-lg text-xs"
      style={{ borderRadius: 12, border: "1px solid #E6EAF1" }}
    >
      <p className="text-muted mb-1">{point.label}</p>
      <p className="font-semibold text-sm" style={{ color: point.color }}>
        AQI : {point.aqi}
      </p>
    </div>
  );
}

export function PredictedTrendChart({ forecast }) {
  const improving = forecast.trend_direction === "improving";
  const lineColor = improving ? "#22C55E" : "#EF4444";

  const data = [
    { label: "Today", aqi: forecast.current_aqi, color: "#101828" },
    ...forecast.forecast.map((h) => ({ label: `+${h.horizon}d`, aqi: h.prediction, color: h.color })),
  ];

  const { ticks: yTicks, niceMax } = buildYAxisTicks(data);

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div />
        <p className="text-sm font-semibold" style={{ color: lineColor }}>
          {improving ? "Expected to improve" : "Expected to worsen"}
        </p>
      </div>
      <Card>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={data} margin={{ top: 10, right: 10, left: 6, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="#EEF1F5" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 12, fill: "#667085" }}
              axisLine={false}
              tickLine={false}
              padding={{ left: 12, right: 12 }}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#667085" }}
              axisLine={false}
              tickLine={false}
              width={44}
              domain={[0, niceMax]}
              ticks={yTicks}
              allowDecimals={false}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ stroke: "#E6EAF1" }} />
            <Line
              type="monotone"
              dataKey="aqi"
              stroke={lineColor}
              strokeWidth={3}
              dot={<ActiveDot />}
              animationDuration={800}
            />
          </LineChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}