"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const fmtDateShort = (iso: string) => {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
};

type Point = {
  date: string;
  completed: number;
  failed: number;
  input_required: number;
};

export function TasksBarChart({ data }: { data: Point[] }) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart
        data={data}
        margin={{ top: 8, right: 4, bottom: 0, left: 0 }}
        barCategoryGap={6}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="currentColor"
          strokeOpacity={0.08}
          vertical={false}
        />
        <XAxis
          dataKey="date"
          tickFormatter={fmtDateShort}
          tick={{ fontSize: 10, fill: "currentColor", opacity: 0.5 }}
          axisLine={false}
          tickLine={false}
          interval="preserveStartEnd"
          minTickGap={20}
        />
        <YAxis
          allowDecimals={false}
          tick={{ fontSize: 10, fill: "currentColor", opacity: 0.5 }}
          axisLine={false}
          tickLine={false}
          width={28}
        />
        <Tooltip
          contentStyle={{
            background: "hsl(var(--popover))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 6,
            fontSize: 12,
          }}
          labelFormatter={(label) => fmtDateShort(String(label))}
          cursor={{ fill: "currentColor", fillOpacity: 0.05 }}
        />
        <Legend
          iconSize={8}
          wrapperStyle={{ fontSize: 11, paddingTop: 4 }}
        />
        <Bar
          dataKey="completed"
          name="Completed"
          stackId="t"
          fill="hsl(var(--chart-2))"
          radius={[0, 0, 0, 0]}
          isAnimationActive={false}
        />
        <Bar
          dataKey="input_required"
          name="HITL"
          stackId="t"
          fill="hsl(var(--chart-4))"
          isAnimationActive={false}
        />
        <Bar
          dataKey="failed"
          name="Failed"
          stackId="t"
          fill="hsl(var(--destructive))"
          radius={[3, 3, 0, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
