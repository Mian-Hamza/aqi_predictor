import { motion } from "framer-motion";
import { Cloudy } from "lucide-react";

// Two rings expand outward and fade, staggered slightly, giving a
// "radar ping" effect behind the icon. The icon itself gently scales up
// and down (a slow "breathe") so it doesn't feel static while data loads.
export default function LoadingScreen() {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4">
      <div className="relative flex items-center justify-center w-16 h-16">
        {[0, 1].map((i) => (
          <motion.span
            key={i}
            className="absolute inset-0 rounded-full bg-accent/20"
            animate={{ scale: [1, 1.9], opacity: [0.55, 0] }}
            transition={{
              duration: 1.8,
              repeat: Infinity,
              delay: i * 0.6,
              ease: "easeOut",
            }}
          />
        ))}

        <motion.div
          className="relative w-12 h-12 rounded-full bg-accent/10 flex items-center justify-center text-accent"
          animate={{ scale: [1, 1.08, 1] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
        >
          <Cloudy size={22} strokeWidth={2.25} />
        </motion.div>
      </div>

      <p className="text-sm text-muted">Loading air quality data…</p>
    </div>
  );
}