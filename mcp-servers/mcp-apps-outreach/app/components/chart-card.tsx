import { REPLY_CLASSES } from "@shared/outreach";
import type { Snapshot } from "@shared/schema";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { formatDate } from "@/lib/format";
import { REPLY_META } from "@/lib/meta";

const chartConfig = Object.fromEntries(
  REPLY_CLASSES.map((c) => [c, { label: REPLY_META[c].label, color: REPLY_META[c].color }]),
) satisfies ChartConfig;

export function ChartCard({ snapshot, className }: { snapshot: Snapshot; className?: string }) {
  const total = snapshot.replies.length;
  const human = snapshot.replies.filter((r) => r.classification !== "out_of_office").length;

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Replies per day</CardTitle>
        <CardDescription>Stacked by how each reply was classified</CardDescription>
        <CardAction className="text-right">
          <div className="tabular text-lg leading-none font-semibold">{total}</div>
          <div className="text-subtle-foreground mt-1 text-[11px]">{human} from people</div>
        </CardAction>
      </CardHeader>
      <CardContent className="flex-1">
        <ChartContainer config={chartConfig} className="aspect-auto h-[232px] w-full">
          <BarChart data={snapshot.series} margin={{ top: 4, right: 4, left: -24, bottom: 0 }} barCategoryGap="18%">
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              minTickGap={24}
              tickFormatter={(value: string) => formatDate(`${value}T00:00:00Z`)}
            />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={40} tickMargin={4} />
            <ChartTooltip
              cursor={{ fillOpacity: 0.6 }}
              content={
                <ChartTooltipContent
                  labelFormatter={(_, payload) => {
                    const date = payload?.[0]?.payload?.date as string | undefined;
                    return date ? formatDate(`${date}T00:00:00Z`) : "";
                  }}
                />
              }
            />
            <ChartLegend content={<ChartLegendContent />} />
            {REPLY_CLASSES.map((c, index) => (
              <Bar
                key={c}
                dataKey={c}
                stackId="replies"
                fill={`var(--color-${c})`}
                radius={index === REPLY_CLASSES.length - 1 ? [3, 3, 0, 0] : 0}
                maxBarSize={28}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
