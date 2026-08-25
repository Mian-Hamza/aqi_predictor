import { motion, useSpring, useTransform } from "framer-motion";
import { useEffect, useState } from "react";
import { useTheme } from "../lib/ThemeContext.jsx";

const MAX_AQI = 300;

const SIZE = 220;
const STROKE = 20;
const RADIUS = (SIZE - STROKE) / 2;
const CENTER = SIZE / 2;
const START_ANGLE = -220; // degrees
const END_ANGLE = 40; // degrees (220deg sweep)

function polarToCartesian(angleDeg) {
  const angleRad = (angleDeg * Math.PI) / 180;
  return {
    x: CENTER + RADIUS * Math.cos(angleRad),
    y: CENTER + RADIUS * Math.sin(angleRad),
  };
}

function arcPath(fromDeg, toDeg) {
  const start = polarToCartesian(fromDeg);
  const end = polarToCartesian(toDeg);
  const largeArc = toDeg - fromDeg <= 180 ? 0 : 1;
  return `M ${start.x} ${start.y} A ${RADIUS} ${RADIUS} 0 ${largeArc} 1 ${end.x} ${end.y}`;
}

function valueToAngle(value) {
  const clamped = Math.max(0, Math.min(MAX_AQI, value));
  const fraction = clamped / MAX_AQI;
  return START_ANGLE + fraction * (END_ANGLE - START_ANGLE);
}

export default function AqiGauge({ value, color }) {
  const { isDark } = useTheme();
  const trackColor = isDark ? "#26303F" : "#EEF1F5";
  const valueTextColor = isDark ? "#F1F5F9" : "#101828";
  const labelTextColor = isDark ? "#94A3B8" : "#667085";

  const spring = useSpring(0, { stiffness: 60, damping: 16 });
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    spring.set(value ?? 0);
  }, [value, spring]);

  useEffect(() => {
    const unsub = spring.on("change", (v) => setDisplay(v));
    return unsub;
  }, [spring]);

  const needleAngle = valueToAngle(display);

  return (
    <div className="flex flex-col items-center">
      <svg width={SIZE} height={SIZE * 0.72} viewBox={`0 0 ${SIZE} ${SIZE * 0.78}`}>
        <path
          d={arcPath(START_ANGLE, END_ANGLE)}
          stroke={trackColor}
          strokeWidth={STROKE}
          fill="none"
          strokeLinecap="round"
        />
        <motion.path
          d={arcPath(START_ANGLE, needleAngle)}
          stroke={color}
          strokeWidth={STROKE}
          fill="none"
          strokeLinecap="round"
        />
        <text
          x={CENTER}
          y={CENTER - 6}
          textAnchor="middle"
          className="font-display"
          style={{ fontSize: 40, fontWeight: 700, fill: valueTextColor }}
        >
          {Math.round(display)}
        </text>
        <text
          x={CENTER}
          y={CENTER + 18}
          textAnchor="middle"
          style={{ fontSize: 12, fill: labelTextColor, letterSpacing: "0.05em" }}
        >
          AQI
        </text>
      </svg>
    </div>
  );
}