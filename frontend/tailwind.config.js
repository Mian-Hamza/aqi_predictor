/** @type {import('tailwindcss').Config} */
export default {
    darkMode: "class",
    content: ["./index.html", "./src/**/*.{js,jsx}"],
    theme: {
      extend: {
        colors: {
          surface: "rgb(var(--color-surface) / <alpha-value>)",
          canvas: "rgb(var(--color-canvas) / <alpha-value>)",
          border: "rgb(var(--color-border) / <alpha-value>)",
          ink: "rgb(var(--color-ink) / <alpha-value>)",
          muted: "rgb(var(--color-muted) / <alpha-value>)",
          accent: "rgb(var(--color-accent) / <alpha-value>)",
          // AQI severity colors are semantic (blue=low ... red=high), not
          // theme-dependent -- they stay identical in light and dark mode,
          // so these are left as plain hex, untouched.
          "aqi-low": "#3B82F6",
          "aqi-medium": "#22C55E",
          "aqi-above": "#EAB308",
          "aqi-high": "#EF4444",
        },
        fontFamily: {
          display: ["'Space Grotesk'", "sans-serif"],
          sans: ["'Inter'", "sans-serif"],
        },
        borderRadius: {
          card: "20px",
        },
        boxShadow: {
          card: "0 1px 2px rgba(16,24,40,0.04), 0 4px 16px rgba(16,24,40,0.05)",
        },
      },
    },
    plugins: [],
  };