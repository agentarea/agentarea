import { ListFrame } from "@kit/components/list";
import { Section } from "@kit/components/section";
import { cn } from "@kit/lib/utils";
import { minorDigits, toMajor } from "@shared/money";
import type { Overview } from "@shared/schema";
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from "recharts";
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/chart";
import { compactMoney, wholeMoney } from "@/lib/format";

const chartConfig = {
  income: { label: "Income", color: "var(--chart-income)" },
  expenses: { label: "Expenses", color: "var(--chart-expense)" },
} satisfies ChartConfig;

export function MonthlyChart({ overview, className }: { overview: Overview; className?: string }) {
  const { baseCurrency: currency, locale } = overview.book;
  const rows = overview.months.map((m) => ({
    ...m,
    short: m.label.slice(0, 3),
    income: toMajor(m.income, currency),
    expenses: toMajor(m.expenses, currency),
  }));
  const shown = overview.months.filter((m) => m.inPeriod);
  const net = shown.reduce((sum, m) => sum + m.net, 0);
  const minor = (value: number) => Math.round(value * 10 ** minorDigits(currency));

  return (
    <Section
      className={className}
      title="Income vs expenses"
      meta={`12 months to ${overview.months.at(-1)?.label}`}
      actions={
        <span className="text-muted-foreground tabular text-xs">
          Net {overview.period.label}{" "}
          <span className={cn("text-foreground font-semibold", net < 0 && "text-danger")}>
            {wholeMoney(net, currency, locale)}
          </span>
        </span>
      }
    >
      <ListFrame className="px-2 pt-3 pb-1">
        <ChartContainer config={chartConfig} className="aspect-auto h-[220px] w-full">
          <BarChart data={rows} margin={{ top: 4, right: 4, left: 0, bottom: 0 }} barCategoryGap="24%" barGap={2}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="short" tickLine={false} axisLine={false} tickMargin={8} minTickGap={8} fontSize={11} />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={72}
              tickMargin={4}
              fontSize={11}
              tickFormatter={(value: number) => compactMoney(minor(value), currency, locale)}
            />
            <ChartTooltip
              cursor={{ fillOpacity: 0.6 }}
              content={
                <ChartTooltipContent
                  labelFormatter={(_, payload) => (payload?.[0]?.payload?.label as string | undefined) ?? ""}
                  valueFormatter={(value) => wholeMoney(minor(value), currency, locale)}
                />
              }
            />
            <ChartLegend content={<ChartLegendContent />} />
            {(["income", "expenses"] as const).map((key) => (
              <Bar
                key={key}
                dataKey={key}
                fill={`var(--color-${key})`}
                radius={[2, 2, 0, 0]}
                maxBarSize={18}
                isAnimationActive={false}
              >
                {rows.map((row) => (
                  <Cell key={row.month} fillOpacity={row.inPeriod ? 1 : 0.4} />
                ))}
              </Bar>
            ))}
          </BarChart>
        </ChartContainer>
      </ListFrame>
    </Section>
  );
}
