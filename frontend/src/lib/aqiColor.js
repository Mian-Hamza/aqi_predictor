// Mirrors backend/main.py's aqi_category() thresholds exactly -- keep these
// in sync if either changes, or the chart colors will disagree with the
// badges/gauge elsewhere in the app.

export function aqiColor(aqi) {
    if (aqi <= 50) return "#3B82F6"; // Low
    if (aqi <= 100) return "#22C55E"; // Medium
    if (aqi <= 150) return "#EAB308"; // Above Medium
    return "#EF4444"; // High
  }
  
  export function aqiCategoryKey(aqi) {
    if (aqi <= 50) return "low";
    if (aqi <= 100) return "medium";
    if (aqi <= 150) return "above";
    return "high";
  }
  
  export const AQI_CATEGORIES = ["low", "medium", "above", "high"];

  // Band definitions used to build value-based color gradients in the trend
  // chart. `from`/`to` delimit the AQI range of each band; colors match
  // aqiColor() above exactly, so the line changes color exactly where the
  // AQI category changes.
  export const AQI_BANDS = [
    { key: "low", label: "Good", from: 0, to: 50, color: "#3B82F6" },
    { key: "medium", label: "Moderate", from: 50, to: 100, color: "#22C55E" },
    { key: "above", label: "Above Medium", from: 100, to: 150, color: "#EAB308" },
    { key: "high", label: "High", from: 150, to: Infinity, color: "#EF4444" },
  ];
