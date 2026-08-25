import { motion } from "framer-motion";
import { RefreshCw, MapPin, Cloudy, Sun, Moon } from "lucide-react";
import { useTheme } from "../lib/ThemeContext.jsx";

function formatTime(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export default function Header({ city, color, updatedAt, onRefresh, refreshing }) {
  const time = formatTime(updatedAt);
  const { isDark, toggleTheme } = useTheme();

  const background = color
    ? isDark
      ? `linear-gradient(135deg, ${color}33 0%, rgba(19,24,35,0.85) 60%)`
      : `linear-gradient(135deg, ${color}26 0%, rgba(255,255,255,0.72) 60%)`
    : isDark
      ? "rgba(19,24,35,0.85)"
      : "rgba(255,255,255,0.72)";

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="sticky top-4 z-50 rounded-card border py-3 px-4 sm:px-6 mb-8 flex items-center justify-between gap-3 backdrop-blur-md shadow-sm"
      style={{
        background,
        borderColor: color ? `${color}33` : "rgb(var(--color-border))",
      }}
    >
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-9 h-9 rounded-full bg-[#006400]/10 dark:bg-[#22c55e]/15 flex items-center justify-center text-[#0ee920] dark:text-[#4ade80] shrink-0">
          <Cloudy size={18} strokeWidth={2.25} />
        </div>
        <div className="min-w-0">
          <h1 className="font-display text-base sm:text-lg font-bold text-ink leading-tight truncate">
           Pearls AQI Predictor
          </h1>
          <p className="text-xs text-muted truncate">Advanced air quality monitoring</p>
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-3 shrink-0">
        {city && (
          <span className="hidden sm:flex items-center gap-1.5 bg-white/70 dark:bg-surface/70 border border-border rounded-full px-3 py-1.5 text-xs font-medium text-ink">
            <MapPin size={12} className="text-muted shrink-0" />
            {city}
          </span>
        )}

        {time && (
          <span className="hidden md:inline text-xs text-muted whitespace-nowrap">
            Updated {time}
          </span>
        )}

        <motion.button
          onClick={toggleTheme}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
          title={isDark ? "Switch to light mode" : "Switch to dark mode"}
          className="flex items-center justify-center bg-white dark:bg-surface border border-border rounded-full w-8 h-8 text-ink shadow-sm hover:shadow-md hover:border-accent/40 transition-all shrink-0"
        >
          {isDark ? <Sun size={14} strokeWidth={2.25} /> : <Moon size={14} strokeWidth={2.25} />}
        </motion.button>

        <motion.button
          onClick={onRefresh}
          disabled={refreshing}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          className="flex items-center gap-1.5 bg-white dark:bg-surface border border-border rounded-full px-3 py-1.5 text-xs sm:text-sm font-medium text-ink shadow-sm hover:shadow-md hover:border-accent/40 transition-all disabled:opacity-50 shrink-0"
        >
          <motion.span
            className="flex text-accent"
            animate={refreshing ? { rotate: 360 } : { rotate: 0 }}
            transition={refreshing ? { repeat: Infinity, duration: 0.8, ease: "linear" } : {}}
          >
            <RefreshCw size={14} strokeWidth={2.25} />
          </motion.span>
          Refresh
        </motion.button>
      </div>
    </motion.div>
  );
}