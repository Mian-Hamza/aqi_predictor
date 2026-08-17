import { motion } from "framer-motion";
import { TriangleAlert, ShieldCheck } from "lucide-react";
import AqiGauge from "./AqiGauge.jsx";
import { Card, Badge } from "./Common.jsx";

export default function CurrentAqiPanel({ current }) {
  const change = current.aqi_change ?? 0;
  const arrow = change > 0 ? "↑" : change < 0 ? "↓" : "→";
  const arrowColor = change > 0 ? "#EF4444" : change < 0 ? "#22C55E" : "#667085";
  const updated = new Date(current.timestamp);

  // "Safe" = Low or Medium, matching the backend's guidance tone (those two
  // categories don't warn about health risk; Above Medium/High do).
  const isSafe = current.category === "Low" || current.category === "Medium";
  const AlertIcon = isSafe ? ShieldCheck : TriangleAlert;
  const alertTitle = isSafe ? "Air Quality Good" : "Air Quality Alert";

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <Card>
        <div className="flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex-1 w-full">
            <p className="text-sm text-muted mb-1">Current Air Quality</p>
            <Badge label={current.category} color={current.color} />

            <div className="mt-6 flex items-baseline gap-2">
              <span className="font-display text-2xl font-bold" style={{ color: arrowColor }}>
                {arrow} {Math.abs(change)}
              </span>
              <span className="text-sm text-muted">pts vs previous reading</span>
            </div>
            <p className="text-xs text-muted mt-1">
              Updated {updated.toLocaleDateString()} at{" "}
              {updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </p>
          </div>

          <AqiGauge value={current.aqi} color={current.color} />
        </div>

        <div
          className="mt-6 rounded-2xl p-4 border flex items-start gap-3"
          style={{ backgroundColor: `${current.color}0D`, borderColor: `${current.color}33` }}
        >
          <span className="mt-0.5" style={{ color: current.color }}>
            <AlertIcon size={18} strokeWidth={2.25} />
          </span>
          <div>
            <p className="font-semibold text-sm text-ink">{alertTitle}</p>
            <p className="text-sm text-muted mt-0.5">{current.guidance}</p>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}