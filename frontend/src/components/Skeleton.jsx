import { Card } from "./Common.jsx";

// Base shimmer block -- every skeleton piece below is built from this.
export function Skeleton({ className = "" }) {
  return <div className={`skeleton rounded-md ${className}`} />;
}

function SectionHeaderSkeleton({ titleWidth = "w-40" }) {
  return (
    <div className="mb-4">
      <Skeleton className={`h-5 ${titleWidth} mb-2`} />
      <Skeleton className="h-3 w-56" />
    </div>
  );
}

// Matches CurrentAqiPanel: left text column + circular gauge + alert strip.
function AqiPanelSkeleton() {
  return (
    <Card>
      <div className="flex flex-col md:flex-row items-center justify-between gap-6">
        <div className="flex-1 w-full">
          <Skeleton className="h-3 w-28 mb-3" />
          <Skeleton className="h-7 w-24 rounded-full mb-6" />
          <Skeleton className="h-7 w-32 mb-2" />
          <Skeleton className="h-3 w-40" />
        </div>
        <Skeleton className="w-40 h-40 rounded-full shrink-0" />
      </div>
      <Skeleton className="h-16 w-full mt-6 rounded-2xl" />
    </Card>
  );
}

// Matches a single StatCard: icon circle + big value + label.
function StatCardSkeleton() {
  return (
    <Card>
      <Skeleton className="w-9 h-9 rounded-full mb-3" />
      <Skeleton className="h-6 w-16 mb-2" />
      <Skeleton className="h-3 w-20" />
    </Card>
  );
}

// Matches the pollutants grid: 6 StatCards, grid-cols-2/3/6 like the real one.
function PollutantsGridSkeleton() {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <StatCardSkeleton key={i} />
      ))}
    </div>
  );
}

// Matches the conditions grid: 4 StatCards, grid-cols-2/4 like the real one.
function ConditionsGridSkeleton() {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <StatCardSkeleton key={i} />
      ))}
    </div>
  );
}

// Matches TrendChart: its own internal 4-stat row + the chart area.
function TrendChartSkeleton() {
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        {Array.from({ length: 4 }).map((_, i) => (
          <StatCardSkeleton key={i} />
        ))}
      </div>
      <Card>
        <div className="flex items-center justify-between mb-3">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-7 w-32 rounded-full" />
        </div>
        <Skeleton className="h-64 w-full rounded-xl" />
        <div className="flex gap-4 mt-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-3 w-16" />
          ))}
        </div>
      </Card>
    </>
  );
}

// Matches ForecastCards: 3 cards, each with a badge + big number + rmse line.
function ForecastCardsSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <div className="flex items-center justify-between mb-3">
            <div>
              <Skeleton className="h-3 w-10 mb-1.5" />
              <Skeleton className="h-4 w-14" />
            </div>
            <Skeleton className="h-6 w-16 rounded-full" />
          </div>
          <Skeleton className="h-8 w-20 mb-3" />
          <Skeleton className="h-3 w-24" />
        </Card>
      ))}
    </div>
  );
}

// Matches the Predicted AQI Trend graph card.
function PredictedTrendSkeleton() {
  return (
    <Card>
      <Skeleton className="h-64 w-full rounded-xl" />
    </Card>
  );
}

// Matches WhyPrediction: header, 3 stat boxes, and a stack of horizontal
// bars with varying widths -- mimicking the actual SHAP chart shape so the
// swap-in doesn't visually "jump" once real data arrives.
function ShapCardSkeleton() {
  const barWidths = ["w-full", "w-3/4", "w-2/3", "w-1/2", "w-2/5", "w-1/3", "w-1/4", "w-1/5"];

  return (
    <Card>
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <Skeleton className="w-9 h-9 rounded-full" />
          <div>
            <Skeleton className="h-4 w-36 mb-1.5" />
            <Skeleton className="h-3 w-48" />
          </div>
        </div>
        <Skeleton className="h-7 w-28 rounded-full" />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="bg-canvas rounded-xl p-3">
            <Skeleton className="h-3 w-20 mb-2" />
            <Skeleton className="h-5 w-16" />
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-3">
        {barWidths.map((w, i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="h-3 w-20 shrink-0" />
            <Skeleton className={`h-4 ${w}`} />
          </div>
        ))}
      </div>
    </Card>
  );
}

// Full-page composition, in the SAME order as App.jsx's real sections, so
// the skeleton reads as a preview of the actual layout rather than a
// generic spinner.
export default function DashboardSkeleton() {
  return (
    <div>
      <div className="mb-8">
        <AqiPanelSkeleton />
      </div>

      <div className="mb-8">
        <SectionHeaderSkeleton titleWidth="w-40" />
        <PollutantsGridSkeleton />
      </div>

      <div className="mb-8">
        <SectionHeaderSkeleton titleWidth="w-48" />
        <TrendChartSkeleton />
      </div>

      <div className="mb-8">
        <SectionHeaderSkeleton titleWidth="w-44" />
        <ConditionsGridSkeleton />
      </div>

      <div className="mb-8">
        <SectionHeaderSkeleton titleWidth="w-52" />
        <ForecastCardsSkeleton />
      </div>

      <div className="mb-8">
        <SectionHeaderSkeleton titleWidth="w-44" />
        <PredictedTrendSkeleton />
      </div>

      <ShapCardSkeleton />
    </div>
  );
}