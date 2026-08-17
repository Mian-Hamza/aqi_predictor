import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { Radio, BarChart3, ArrowDown, ArrowUp } from "lucide-react";
import { Card, StatCard } from "./Common.jsx";
import { aqiColor, aqiCategoryKey, AQI_CATEGORIES } from "../lib/aqiColor.js";
function formatHour(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatFull(iso) {
  const d = new Date(iso);
  const datePart = d.toLocaleDateString([], { month: "short", day: "numeric" });
  const timePart = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `${datePart} · ${timePart}`;
}

/**
 * Recharts doesn't support coloring a single line "by value" out of the box.
 * The standard workaround: split the data into one parallel series per AQI
 * category (low/medium/above/high), each holding the real value only where
 * that category applies (undefined elsewhere), then render one <Area> per
 * category with its own color. Boundary points are duplicated into BOTH
 * adjacent series so the colored segments visually join with no gaps.
 */
function buildColoredSeries(points) {
  const enriched = points.map((p) => ({ ...p, category: aqiCategoryKey(p.aqi) }));

  return enriched.map((p, i) => {
    const row = { ...p };
    const prev = enriched[i - 1];
    const next = enriched[i + 1];

    row[`aqi_${p.category}`] = p.aqi;
    if (prev && prev.category !== p.category) row[`aqi_${prev.category}`] = p.aqi;
    if (next && next.category !== p.category) row[`aqi_${next.category}`] = p.aqi;

    return row;
  });
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0].payload;
  const color = aqiColor(point.aqi);

  return (
    <div className="bg-white border border-border rounded-lg px-3 py-2 shadow-lg">
      <p className="text-xs text-muted mb-0.5">{formatFull(point.timestamp)}</p>
      <p className="font-semibold text-sm" style={{ color }}>
        AQI {point.aqi}
      </p>
    </div>
  );
}

export default function TrendChart({ trend, color }) {
  const rawData = trend.points.map((p) => ({ ...p, hourLabel: formatHour(p.timestamp) }));
  const data = buildColoredSeries(rawData);

  return (
    <div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatCard label="Current" value={trend.current} index={0} icon={Radio} valueColor={aqiColor(trend.current)} />
        <StatCard label="Average" value={trend.avg} index={1} icon={BarChart3} valueColor={aqiColor(trend.avg)} />
        <StatCard label="Minimum" value={trend.min} index={2} icon={ArrowDown} valueColor={aqiColor(trend.min)} />
        <StatCard label="Maximum" value={trend.max} index={3} icon={ArrowUp} valueColor={aqiColor(trend.max)} />
      </div>

      <Card>
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={data} margin={{ top: 10, right: 10, left: 6, bottom: 0 }}>
            <defs>
              {AQI_CATEGORIES.map((cat) => (
                <linearGradient key={cat} id={`trendFill-${cat}`} x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor={aqiColor(cat === "low" ? 25 : cat === "medium" ? 75 : cat === "above" ? 125 : 200)}
                    stopOpacity={0.28}
                  />
                  <stop
                    offset="100%"
                    stopColor={aqiColor(cat === "low" ? 25 : cat === "medium" ? 75 : cat === "above" ? 125 : 200)}
                    stopOpacity={0}
                  />
                </linearGradient>
              ))}
            </defs>

            <CartesianGrid vertical={false} stroke="#EEF1F5" />
            <XAxis
              dataKey="hourLabel"
              tick={{ fontSize: 11, fill: "#667085" }}
              interval={Math.ceil(data.length / 6)}
              axisLine={false}
              tickLine={false}
              padding={{ left: 12, right: 12 }}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#667085" }}
              axisLine={false}
              tickLine={false}
              width={44}
              domain={[0, (max) => Math.ceil((max + 20) / 50) * 50]}
              allowDecimals={false}
            />
            <Tooltip content={<CustomTooltip />} />

            {AQI_CATEGORIES.map((cat) => (
              <Area
                key={cat}
                type="monotone"
                dataKey={`aqi_${cat}`}
                stroke={aqiColor(cat === "low" ? 25 : cat === "medium" ? 75 : cat === "above" ? 125 : 200)}
                strokeWidth={2.5}
                fill={`url(#trendFill-${cat})`}
                connectNulls={false}
                animationDuration={800}
                isAnimationActive={true}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}