import { motion } from "framer-motion";
import { RefreshCw, MapPin, Cloudy } from "lucide-react";

function formatTime(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export default function Header({ city, color, updatedAt, onRefresh, refreshing }) {
  const time = formatTime(updatedAt);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="sticky top-4 z-50 rounded-card border py-3 px-4 sm:px-6 mb-8 flex items-center justify-between gap-3 backdrop-blur-md shadow-sm"
      style={{
        background: color
          ? `linear-gradient(135deg, ${color}26 0%, rgba(255,255,255,0.72) 60%)`
          : "rgba(255,255,255,0.72)",
        borderColor: color ? `${color}33` : "#E6EAF1",
      }}
    >
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-9 h-9 rounded-full bg-[#006400]/10 flex items-center justify-center text-[#0ee920] shrink-0">
          <Cloudy size={18} strokeWidth={2.25} />
        </div>
        <div className="min-w-0">
          <h1 className="font-display text-base sm:text-lg font-bold text-ink leading-tight truncate">
           Pearls AQI Predictor
          </h1>
          <p className="text-xs text-muted truncate">AI-powered air quality intelligence</p>
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-3 shrink-0">
        {city && (
          <span className="hidden sm:flex items-center gap-1.5 bg-white/70 border border-border rounded-full px-3 py-1.5 text-xs font-medium text-ink">
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
          onClick={onRefresh}
          disabled={refreshing}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          className="flex items-center gap-1.5 bg-white border border-border rounded-full px-3 py-1.5 text-xs sm:text-sm font-medium text-ink shadow-sm hover:shadow-md hover:border-accent/40 transition-all disabled:opacity-50 shrink-0"
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