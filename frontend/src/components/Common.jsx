import { motion } from "framer-motion";

export function Section({ title, caption, children, className = "" }) {
  return (
    <section className={`mb-8 ${className}`}>
      <h2 className="font-display text-xl font-semibold text-ink">{title}</h2>
      {caption && <p className="text-sm text-muted mb-4">{caption}</p>}
      {!caption && <div className="mb-4" />}
      {children}
    </section>
  );
}

export function Card({ children, className = "" }) {
  return (
    <div
      className={`bg-surface border border-border rounded-card shadow-card p-5 h-full ${className}`}
    >
      {children}
    </div>
  );
}

export function StatCard({ icon: Icon, label, value, unit, index = 0, valueColor }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, duration: 0.35 }}
      whileHover={{ y: -3 }}
    >
      <Card>
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center mb-3"
          style={{
            backgroundColor: valueColor ? `${valueColor}1A` : undefined,
            color: valueColor || undefined,
          }}
        >
          <Icon size={18} strokeWidth={2.25} className={valueColor ? undefined : "text-accent"} />
        </div>
        <div
          className="font-display text-2xl font-bold tabular-nums"
          style={{ color: valueColor || "#101828" }}
        >
          {value ?? "—"}
          {unit && <span className="text-sm font-medium text-muted ml-1">{unit}</span>}
        </div>
        <div className="text-sm text-muted mt-1">{label}</div>
      </Card>
    </motion.div>
  );
}

export function Badge({ label, color }) {
  return (
    <span
      className="inline-block px-3 py-1 rounded-full text-xs font-semibold"
      style={{ backgroundColor: `${color}1A`, color, border: `1px solid ${color}40` }}
    >
      {label}
    </span>
  );
}