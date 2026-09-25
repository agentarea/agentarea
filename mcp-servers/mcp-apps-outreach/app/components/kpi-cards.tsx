import type { Kpi, Snapshot } from "@shared/schema";
import {
  ArrowDownRight,
  ArrowUpRight,
  CalendarCheck,
  DollarSign,
  type LucideIcon,
  Minus,
  Radio,
  Reply,
  Send,
  ThumbsUp,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/format";

const ICONS: Record<Kpi["key"], LucideIcon> = {
  signals: Radio,
  contacted: Send,
  reply_rate: Reply,
  positive: ThumbsUp,
  meetings: CalendarCheck,
  pipeline: DollarSign,
};

function formatValue(kpi: Pick<Kpi, "format">, value: number) {
  if (kpi.format === "percent") return formatPercent(value);
  if (kpi.format === "currency") return formatCurrency(value);
  return formatNumber(value);
}

function Delta({ kpi, period }: { kpi: Kpi; period: number }) {
  if (kpi.previous === null) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="muted" className="cursor-help">
            no baseline
          </Badge>
        </TooltipTrigger>
        <TooltipContent>The dataset doesn't cover the {period} days before this period.</TooltipContent>
      </Tooltip>
    );
  }
  // Rates compare in percentage points; counts compare relatively.
  const change =
    kpi.format === "percent"
      ? (kpi.value - kpi.previous) * 100
      : kpi.previous === 0
        ? kpi.value === 0
          ? 0
          : null
        : ((kpi.value - kpi.previous) / kpi.previous) * 100;
  const direction = change === null || change > 0.05 ? "up" : change < -0.05 ? "down" : "flat";
  const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus;
  const label =
    change === null
      ? "new"
      : `${change > 0 ? "+" : ""}${Math.abs(change) >= 10 ? change.toFixed(0) : change.toFixed(1)}${kpi.format === "percent" ? " pp" : "%"}`;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          variant={direction === "up" ? "success" : direction === "down" ? "danger" : "muted"}
          className="tabular cursor-help gap-0.5 pl-1"
        >
          <Icon />
          {label}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>
        Previous {period} days: {formatValue(kpi, kpi.previous)}
      </TooltipContent>
    </Tooltip>
  );
}

export function KpiCards({ snapshot }: { snapshot: Snapshot }) {
  return (
    <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {snapshot.kpis.map((kpi) => {
        const Icon = ICONS[kpi.key];
        return (
          <Card key={kpi.key} className="gap-0 px-4 py-3.5">
            <div className="text-muted-foreground flex items-center justify-between gap-2 text-xs font-medium">
              <span className="truncate">{kpi.label}</span>
              <Icon className="text-subtle-foreground size-3.5 shrink-0" />
            </div>
            <div className="mt-2 flex items-end justify-between gap-2">
              <span className="tabular text-2xl leading-none font-semibold tracking-tight">
                {formatValue(kpi, kpi.value)}
              </span>
              <Delta kpi={kpi} period={snapshot.period} />
            </div>
            <p className="text-subtle-foreground tabular mt-2 text-[11px]">
              prev. {snapshot.period}d: {kpi.previous === null ? "—" : formatValue(kpi, kpi.previous)}
            </p>
          </Card>
        );
      })}
    </section>
  );
}
