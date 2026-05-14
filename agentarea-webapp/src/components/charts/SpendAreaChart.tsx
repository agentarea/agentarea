"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const fmtUsd = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

const fmtDateShort = (iso: string) => {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
};

type Point = { date: string; usd: number };

export function SpendAreaChart({
  data,
  height = 110,
}: {
  data: Point[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart
        data={data}
        margin={{ top: 6, right: 6, bottom: 0, left: 0 }}
      >
        <defs>
          <linearGradient id="spendGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.18} />
            <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="date"
          tickFormatter={fmtDateShort}
          tick={{ fontSize: 10, fill: "currentColor", opacity: 0.45 }}
          axisLine={false}
          tickLine={false}
          interval="preserveStartEnd"
          minTickGap={36}
          padding={{ left: 4, right: 4 }}
        />
        <YAxis hide />
        <Tooltip
          contentStyle={{
            background: "hsl(var(--popover))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 6,
            fontSize: 12,
            padding: "6px 8px",
            boxShadow: "0 4px 16px rgba(0,0,0,0.06)",
          }}
          labelStyle={{ color: "hsl(var(--muted-foreground))", fontSize: 11 }}
          itemStyle={{ color: "hsl(var(--foreground))" }}
          labelFormatter={(label) => fmtDateShort(String(label))}
          formatter={(v) => [fmtUsd(Number(v)), "Spend"]}
          cursor={{ stroke: "currentColor", strokeOpacity: 0.12, strokeDasharray: "3 3" }}
        />
        <Area
          type="monotone"
          dataKey="usd"
          stroke="hsl(var(--accent))"
          strokeWidth={1.75}
          fill="url(#spendGradient)"
          activeDot={{
            r: 3,
            stroke: "hsl(var(--background))",
            strokeWidth: 1.5,
            fill: "hsl(var(--accent))",
          }}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
