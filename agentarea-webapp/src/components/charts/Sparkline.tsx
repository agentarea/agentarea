// Smooth SVG sparkline using monotone-cubic interpolation. Pure SVG,
// no deps. Reserved for inline trend hints next to numbers — recharts
// handles the few "hero" charts where axes / tooltips matter.

import { cn } from "@/lib/utils";

type Props = {
  values: number[];
  width?: number;
  height?: number;
  stroke?: string;
  strokeWidth?: number;
  showDot?: boolean;
  /** When set, fills the area under the curve with this color. */
  fill?: string;
  /** Opacity of the area fill (default 0.13). */
  fillOpacity?: number;
  className?: string;
};

// Monotone cubic Hermite interpolation (Fritsch-Carlson). Produces a
// natural-looking curve without overshoot — same approach Recharts uses
// for `type="monotone"`. ~30 lines, well-tested in the wild.
function monotoneCubicPath(points: { x: number; y: number }[]): string {
  const n = points.length;
  if (n === 0) return "";
  if (n === 1) return `M${points[0].x},${points[0].y}`;

  const dx = new Array(n - 1).fill(0);
  const dy = new Array(n - 1).fill(0);
  const slope = new Array(n - 1).fill(0);
  for (let i = 0; i < n - 1; i++) {
    dx[i] = points[i + 1].x - points[i].x;
    dy[i] = points[i + 1].y - points[i].y;
    slope[i] = dx[i] === 0 ? 0 : dy[i] / dx[i];
  }

  const m = new Array(n).fill(0);
  m[0] = slope[0];
  m[n - 1] = slope[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = (slope[i - 1] + slope[i]) / 2;

  for (let i = 0; i < n - 1; i++) {
    if (slope[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / slope[i];
    const b = m[i + 1] / slope[i];
    const h = Math.hypot(a, b);
    if (h > 3) {
      const t = 3 / h;
      m[i] = t * a * slope[i];
      m[i + 1] = t * b * slope[i];
    }
  }

  let d = `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`;
  for (let i = 0; i < n - 1; i++) {
    const c1x = points[i].x + dx[i] / 3;
    const c1y = points[i].y + (m[i] * dx[i]) / 3;
    const c2x = points[i + 1].x - dx[i] / 3;
    const c2y = points[i + 1].y - (m[i + 1] * dx[i]) / 3;
    d += ` C${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${points[i + 1].x.toFixed(2)},${points[i + 1].y.toFixed(2)}`;
  }
  return d;
}

export function Sparkline({
  values,
  width = 80,
  height = 24,
  stroke = "currentColor",
  strokeWidth = 1.5,
  showDot = true,
  fill,
  fillOpacity = 0.13,
  className,
}: Props) {
  if (values.length === 0) {
    return (
      <span
        className={cn("inline-block", className)}
        style={{ width, height }}
      />
    );
  }

  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const range = Math.max(max - min, 1e-9);
  const padY = strokeWidth + 1;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((v, i) => ({
    x: i * step,
    y: height - padY - ((v - min) / range) * (height - padY * 2),
  }));
  const d = monotoneCubicPath(points);
  const last = points[points.length - 1];
  const areaD =
    fill && points.length > 1
      ? `${d} L${last.x.toFixed(2)},${height} L${points[0].x.toFixed(2)},${height} Z`
      : null;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("inline-block align-middle", className)}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {areaD && (
        <path d={areaD} fill={fill} fillOpacity={fillOpacity} stroke="none" />
      )}
      <path
        d={d}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      {showDot && (
        <circle
          cx={last.x}
          cy={last.y}
          r={2}
          fill={stroke}
        />
      )}
    </svg>
  );
}

export type DeltaDirection = "up" | "down" | "flat";

export function computeDelta(
  values: number[],
  comparePeriod = 1
): { delta: number | null; pct: number | null; direction: DeltaDirection } {
  if (values.length < comparePeriod + 1) {
    return { delta: null, pct: null, direction: "flat" };
  }
  const current = values[values.length - 1];
  const prior = values[values.length - 1 - comparePeriod];
  const delta = current - prior;
  const pct = prior !== 0 ? (delta / prior) * 100 : delta !== 0 ? Infinity : 0;
  const direction: DeltaDirection =
    Math.abs(delta) < 1e-9 ? "flat" : delta > 0 ? "up" : "down";
  return { delta, pct, direction };
}

export function DeltaBadge({
  pct,
  direction,
  goodDirection = "up",
}: {
  pct: number | null;
  direction: DeltaDirection;
  goodDirection?: "up" | "down";
}) {
  if (pct === null || direction === "flat") {
    return <span className="text-xs text-muted-foreground tabular-nums">—</span>;
  }
  const isGood =
    (goodDirection === "up" && direction === "up") ||
    (goodDirection === "down" && direction === "down");
  const arrow = direction === "up" ? "↑" : "↓";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 tabular-nums text-xs font-medium",
        isGood
          ? "text-emerald-600 dark:text-emerald-400"
          : "text-red-600 dark:text-red-400"
      )}
    >
      <span>{arrow}</span>
      <span>
        {Number.isFinite(pct) ? `${Math.abs(pct).toFixed(0)}%` : "new"}
      </span>
    </span>
  );
}
