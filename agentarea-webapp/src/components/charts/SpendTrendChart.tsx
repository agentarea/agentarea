"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatMoney } from "@/lib/money";

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
 * Hero spend chart — one violet bar per day with horizontal gridlines, a money
 * Y axis and a date X axis, so a day that spent more than usual stands out.
 * Hovering shows that day's spend. Distinct from the compact inline `Sparkline`.
 *
 * `locale` is passed explicitly (rather than read from browser defaults) so the
 * month labels follow the app's active language, not the OS locale.
 */
export function SpendTrendChart({
  data,
  height = 190,
  locale = "en",
  currency = null,
  seriesLabel = "Spend",
}: {
  data: Point[];
  height?: number | `${number}%`;
  locale?: string;
  currency?: string | null;
  seriesLabel?: string;
}) {
  const fmtAxis = (v: number) =>
    formatMoney(v, currency, locale, { compact: true });

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data ?? []}
        margin={{ top: 10, right: 8, bottom: 0, left: 24 }}
        barCategoryGap="18%"
      >
        <CartesianGrid
          vertical={false}
          stroke="currentColor"
          strokeOpacity={0.12}
          className="text-muted-foreground"
        />
        <YAxis
          domain={[0, "auto"]}
          tickCount={3}
          tickFormatter={(v) => fmtAxis(Number(v))}
          tick={{ fontSize: 10.5, fill: "currentColor", opacity: 0.5 }}
          axisLine={false}
          tickLine={false}
          width="auto"
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
          labelFormatter={(label) => fmtDateShort(String(label), locale)}
          formatter={(v) => [
            formatMoney(Number(v), currency, locale),
            seriesLabel,
          ]}
          cursor={{ fill: "var(--violet)", fillOpacity: 0.08 }}
        />
        <Bar
          dataKey="usd"
          fill="var(--violet)"
          radius={[3, 3, 0, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
