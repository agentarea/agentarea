"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const fmtUsd = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(v);

const fmtDateShort = (iso: string, locale: string) => {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString(locale, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
};

type Point = { date: string; usd: number };

/**
 * Hero spend chart — a cumulative violet area with horizontal gridlines,
 * a dollar Y axis and a date X axis. Hovering shows the running total with a
 * dashed cursor. Distinct from the compact inline `Sparkline`.
 *
 * `locale` is passed explicitly (rather than read from browser defaults) so the
 * month labels follow the app's active language, not the OS locale.
 */
export function SpendTrendChart({
  data,
  height = 190,
  locale = "en",
  seriesLabel = "Spend",
  cumulativeLabel = "cumulative",
}: {
  data: Point[];
  height?: number;
  locale?: string;
  seriesLabel?: string;
  cumulativeLabel?: string;
}) {
  let running = 0;
  const cumulative = (data ?? []).map((p) => {
    running += p.usd;
    return { date: p.date, cum: +running.toFixed(2) };
  });

  const total = cumulative.length ? cumulative[cumulative.length - 1].cum : 0;
  const maxY = Math.max(10, Math.ceil(total / 10) * 10);
  const ticks = [0, maxY / 2, maxY];

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={cumulative} margin={{ top: 10, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="spendTrendFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--violet)" stopOpacity={0.2} />
            <stop offset="100%" stopColor="var(--violet)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid
          vertical={false}
          stroke="currentColor"
          strokeOpacity={0.12}
          className="text-muted-foreground"
        />
        <YAxis
          domain={[0, maxY]}
          ticks={ticks}
          tickFormatter={(v) => `$${v}`}
          tick={{ fontSize: 10.5, fill: "currentColor", opacity: 0.5 }}
          axisLine={false}
          tickLine={false}
          width={40}
          className="text-muted-foreground [&_text]:font-mono"
        />
        <XAxis
          dataKey="date"
          tickFormatter={(v) => fmtDateShort(String(v), locale)}
          tick={{ fontSize: 11, fill: "currentColor", opacity: 0.5 }}
          axisLine={false}
          tickLine={false}
          interval="preserveStartEnd"
          minTickGap={44}
          padding={{ left: 4, right: 4 }}
          className="text-muted-foreground [&_text]:font-mono"
        />
        <Tooltip
          contentStyle={{
            background: "hsl(var(--popover))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 9,
            fontSize: 12.5,
            padding: "7px 10px",
            boxShadow: "0 8px 28px rgba(0,0,0,0.12)",
          }}
          labelStyle={{ color: "hsl(var(--muted-foreground))", fontSize: 11 }}
          itemStyle={{ color: "hsl(var(--foreground))", fontWeight: 600 }}
          labelFormatter={(label) =>
            `${fmtDateShort(String(label), locale)} · ${cumulativeLabel}`
          }
          formatter={(v) => [fmtUsd(Number(v)), seriesLabel]}
          cursor={{
            stroke: "var(--violet)",
            strokeOpacity: 0.5,
            strokeWidth: 1.3,
            strokeDasharray: "4 4",
          }}
        />
        <Area
          type="monotone"
          dataKey="cum"
          stroke="var(--violet)"
          strokeWidth={2.2}
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="url(#spendTrendFill)"
          activeDot={{
            r: 4,
            stroke: "hsl(var(--background))",
            strokeWidth: 2.5,
            fill: "var(--violet)",
          }}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
