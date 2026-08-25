import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { Radio, BarChart3, ArrowDown, ArrowUp } from "lucide-react";
import { Card, StatCard } from "./Common.jsx";
import { aqiColor, AQI_BANDS } from "../lib/aqiColor.js";
import { useTheme } from "../lib/ThemeContext.jsx";

export const TREND_RANGES = [24, 48, 72];

// Chart geometry. These MUST match the props passed to <AreaChart>/<XAxis>
// below, because the color gradient is positioned in absolute pixel space
// (gradientUnits="userSpaceOnUse") -- that is the only way to make the
// gradient track the Y AXIS scale instead of the drawn path's bounding box.
const CHART_HEIGHT = 280;
const CHART_MARGIN = { top: 10, right: 10, left: 6, bottom: 0 };
const X_AXIS_HEIGHT = 30;
const PLOT_TOP = CHART_MARGIN.top;
const PLOT_BOTTOM = CHART_HEIGHT - CHART_MARGIN.bottom - X_AXIS_HEIGHT;

function formatTick(iso, longRange) {
  const d = new Date(iso);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (!longRange) return time;
  return `${d.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

function formatFull(iso) {
  const d = new Date(iso);
  const datePart = d.toLocaleDateString([], { month: "short", day: "numeric" });
  const timePart = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `${datePart} · ${timePart}`;
}

// Evenly spaced ticks (step of 50) derived from the real data range, so the
// gradient band boundaries (50 / 100 / 150) always land on a gridline.
function buildYAxis(data) {
  const maxAqi = data.length ? Math.max(...data.map((d) => d.aqi ?? 0)) : 0;
  const niceMax = Math.max(150, Math.ceil((maxAqi + 20) / 50) * 50);
  const ticks = [];
  for (let v = 0; v <= niceMax; v += 50) ticks.push(v);
  return { ticks, niceMax };
}

/**
 * Previously the line was drawn as four PARALLEL series (one per AQI
 * category), with boundary points copied into both adjacent series so the
 * colored pieces would join up. That copying meant the segment across a
 * boundary existed in BOTH series, so e.g. the red line and the amber line
 * were literally drawn on top of each other -- the visible "overlap".
 *
 * Instead we now draw ONE series and color it by value using an SVG
 * gradient with hard stops at the category thresholds, positioned in the
 * chart's own pixel space. One path, one stroke -> overlap is impossible,
 * and the color still changes exactly where the AQI category changes.
 */
function buildGradientStops(niceMax) {
  const pct = (value) => `${(((niceMax - value) / niceMax) * 100).toFixed(4)}%`;

  const stops = [];
  // Walk the bands from the TOP of the axis downwards, emitting two stops
  // per band (its upper and lower edge) so each transition is a hard cut.
  AQI_BANDS.filter((band) => band.from < niceMax)
    .slice()
    .reverse()
    .forEach((band) => {
      stops.push({ offset: pct(Math.min(band.to, niceMax)), color: band.color });
      stops.push({ offset: pct(band.from), color: band.color });
    });

  return stops;
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0].payload;
  const color = aqiColor(point.aqi);

  return (
    <div className="bg-white dark:bg-surface border border-border rounded-lg px-3 py-2 shadow-lg">
      <p className="text-xs text-muted mb-0.5">{formatFull(point.timestamp)}</p>
      <p className="font-semibold text-sm" style={{ color }}>
        AQI {point.aqi}
      </p>
    </div>
  );
}

function RangeSelector({ value, onChange, disabled }) {
  return (
    <div className="inline-flex bg-canvas border border-border rounded-full p-1">
      {TREND_RANGES.map((hours) => {
        const active = hours === value;
        return (
          <button
            key={hours}
            type="button"
            disabled={disabled}
            onClick={() => onChange(hours)}
            aria-pressed={active}
            className={`px-3 py-1 text-xs font-semibold rounded-full transition-colors ${
              active ? "bg-white dark:bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"
            } ${disabled ? "opacity-60 cursor-not-allowed" : ""}`}
          >
            {hours}H
          </button>
        );
      })}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-4">
      {AQI_BANDS.map((band) => (
        <span key={band.key} className="flex items-center gap-1.5 text-xs text-muted">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: band.color }} />
          {band.label}
        </span>
      ))}
    </div>
  );
}

export default function TrendChart({ trend, hours = 24, onHoursChange, loading = false }) {
  const { isDark } = useTheme();
  const gridStroke = isDark ? "#1F2937" : "#EEF1F5";
  const tickColor = isDark ? "#94A3B8" : "#667085";
  const cursorStroke = isDark ? "#26303F" : "#E6EAF1";

  const longRange = hours > 24;
  const data = trend.points.map((p) => ({ ...p, hourLabel: formatTick(p.timestamp, longRange) }));
  const { ticks: yTicks, niceMax } = buildYAxis(data);
  const stops = buildGradientStops(niceMax);
  const gradientId = `trendStroke-${niceMax}`;
  const fillId = `trendFill-${niceMax}`;

  return (
    <div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatCard label="Current" value={trend.current} index={0} icon={Radio} valueColor={aqiColor(trend.current)} />
        <StatCard label="Average" value={trend.avg} index={1} icon={BarChart3} valueColor={aqiColor(trend.avg)} />
        <StatCard label="Minimum" value={trend.min} index={2} icon={ArrowDown} valueColor={aqiColor(trend.min)} />
        <StatCard label="Maximum" value={trend.max} index={3} icon={ArrowUp} valueColor={aqiColor(trend.max)} />
      </div>

      <Card>
        <div className="flex items-center justify-between gap-3 mb-3">
          <p className="text-sm font-semibold text-ink">
            Last {hours} hours
            {loading && <span className="ml-2 text-xs font-medium text-muted">updating…</span>}
          </p>
          {onHoursChange && <RangeSelector value={hours} onChange={onHoursChange} disabled={loading} />}
        </div>

        <div style={{ opacity: loading ? 0.5 : 1, transition: "opacity 200ms" }}>
          <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
            <AreaChart data={data} margin={CHART_MARGIN}>
              <defs>
                {/* Positioned against the plot area in pixels, so a given
                    AQI value always maps to the same gradient offset. */}
                <linearGradient
                  id={gradientId}
                  gradientUnits="userSpaceOnUse"
                  x1="0"
                  y1={PLOT_TOP}
                  x2="0"
                  y2={PLOT_BOTTOM}
                >
                  {stops.map((s, i) => (
                    <stop key={i} offset={s.offset} stopColor={s.color} />
                  ))}
                </linearGradient>

                <linearGradient
                  id={fillId}
                  gradientUnits="userSpaceOnUse"
                  x1="0"
                  y1={PLOT_TOP}
                  x2="0"
                  y2={PLOT_BOTTOM}
                >
                  {stops.map((s, i) => (
                    <stop key={i} offset={s.offset} stopColor={s.color} stopOpacity={0.16} />
                  ))}
                </linearGradient>
              </defs>

              <CartesianGrid vertical={false} stroke={gridStroke} />
              <XAxis
                dataKey="hourLabel"
                height={X_AXIS_HEIGHT}
                tick={{ fontSize: 11, fill: tickColor }}
                interval={Math.max(0, Math.ceil(data.length / 6) - 1)}
                axisLine={false}
                tickLine={false}
                padding={{ left: 12, right: 12 }}
                minTickGap={12}
              />
              <YAxis
                tick={{ fontSize: 11, fill: tickColor }}
                axisLine={false}
                tickLine={false}
                width={44}
                domain={[0, niceMax]}
                ticks={yTicks}
                allowDecimals={false}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ stroke: cursorStroke }} />

              <Area
                type="monotone"
                dataKey="aqi"
                stroke={`url(#${gradientId})`}
                strokeWidth={2.5}
                fill={`url(#${fillId})`}
                fillOpacity={1}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: isDark ? "#131826" : "#fff" }}
                animationDuration={600}
                isAnimationActive={true}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <Legend />
      </Card>
    </div>
  );
}