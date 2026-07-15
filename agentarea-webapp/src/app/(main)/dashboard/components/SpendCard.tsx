import { AlertTriangle } from "lucide-react";
import { SpendAreaChart } from "@/components/charts/SpendAreaChart";
import { computeDelta, DeltaBadge } from "@/components/charts/Sparkline";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { DailySpendPoint, DashboardSpend } from "@/lib/api-dashboard";

const fmt = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

function pctTone(pct: number) {
  if (pct >= 100) return "text-red-600 dark:text-red-400";
  if (pct >= 80) return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
}

function progressTone(pct: number) {
  if (pct >= 100) return "[&>div]:bg-red-500";
  if (pct >= 80) return "[&>div]:bg-amber-500";
  return "[&>div]:bg-foreground/70";
}

export function SpendCard({
  spend,
  trend,
}: {
  spend: DashboardSpend;
  trend: DailySpendPoint[];
}) {
  const hasCap = spend.cap_usd !== null;
  const pct = spend.pct_of_cap ?? 0;
  const blocked = hasCap && pct >= 100;
  const warn = hasCap && pct >= 80;

  const trendValues = (trend ?? []).map((p) => p.usd);
  const delta = computeDelta(trendValues, 1);

  return (
    <section>
      <header className="flex items-baseline justify-between">
        <h3 className="text-[13px] font-medium text-foreground">Spend</h3>
        <span className="text-[11px] text-muted-foreground tabular-nums">
          Month to date
        </span>
      </header>

      <div className="mt-2 flex items-baseline gap-3">
        <span className="text-[28px] font-semibold leading-none tabular-nums tracking-tight">
          {fmt(spend.mtd_usd)}
        </span>
        <DeltaBadge
          pct={delta.pct}
          direction={delta.direction}
          goodDirection="down"
        />
        <div className="ml-auto text-right text-[11px] text-muted-foreground tabular-nums">
          <div>{fmt(spend.today_usd)} today</div>
          {hasCap && (
            <div className={cn("font-medium", pctTone(pct))}>
              {pct.toFixed(1)}% of {fmt(spend.cap_usd ?? 0)}
            </div>
          )}
        </div>
      </div>

      <div className="mt-3">
        <SpendAreaChart data={trend} height={96} />
      </div>

      {hasCap && (
        <Progress
          value={Math.min(pct, 100)}
          className={cn("mt-3 h-[3px]", progressTone(pct))}
        />
      )}

      {warn && (
        <div
          className={cn(
            "mt-3 flex items-start gap-2 rounded border-l-2 px-3 py-2 text-[11px]",
            blocked
              ? "border-red-500 bg-red-50/60 text-red-900 dark:bg-red-950/30 dark:text-red-200"
              : "border-amber-500 bg-amber-50/60 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
          )}
        >
          <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0" />
          <span>
            {blocked
              ? "Cap reached — new tasks blocked. Raise the cap in workspace settings."
              : `${pct.toFixed(0)}% used — block triggers at 100%.`}
          </span>
        </div>
      )}
    </section>
  );
}
