import { useLocale, useTranslations } from "next-intl";
import { Wallet } from "lucide-react";
import { BoardSectionHeader } from "@/components/board";
import { computeDelta, DeltaBadge } from "@/components/charts/Sparkline";
import { SpendTrendChart } from "@/components/charts/SpendTrendChart";
import { cn } from "@/lib/utils";
import type { DailySpendPoint, DashboardSpend } from "@/lib/api-dashboard";

const fmt = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

function barTone(pct: number) {
  if (pct >= 100) return "bg-[color:var(--status-danger)]";
  if (pct >= 80) return "bg-[color:var(--status-warning)]";
  return "bg-[color:var(--violet)]";
}

function pctTone(pct: number) {
  if (pct >= 100) return "text-red-600 dark:text-red-400";
  if (pct >= 80) return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
}

export function SpendCard({
  spend,
  trend,
  compact = false,
}: {
  spend: DashboardSpend;
  trend: DailySpendPoint[];
  compact?: boolean;
}) {
  const t = useTranslations("DashboardPage");
  const locale = useLocale();
  const hasCap = spend.cap_usd !== null;
  const pct = spend.pct_of_cap ?? 0;

  const trendValues = (trend ?? []).map((p) => p.usd);
  const delta = computeDelta(trendValues, 1);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BoardSectionHeader
        icon={<Wallet />}
        color="hsl(var(--foreground))"
        title={t("spend")}
        meta={t("monthToDate")}
      />

      <div className={cn("flex items-start gap-3.5", compact ? "mt-1" : "mt-1.5")}>
        <div>
          <div
            className={cn(
              "font-semibold leading-[0.95] tracking-[-0.03em] tabular-nums",
              compact ? "text-[24px]" : "text-[27px]"
            )}
          >
            {fmt(spend.mtd_usd)}
          </div>
          <div
            className={cn(
              "flex items-center gap-2 text-[12.5px] text-muted-foreground",
              compact ? "mt-1" : "mt-1.5"
            )}
          >
            <DeltaBadge
              pct={delta.pct}
              direction={delta.direction}
              goodDirection="down"
            />
            <span>{t("vsPrevDay")}</span>
          </div>
        </div>

        <div className={cn("ml-auto text-right", compact ? "pt-0" : "pt-0.5")}>
          <div className="text-[11.5px] text-muted-foreground">{t("today")}</div>
          <div className="mt-0.5 text-[15px] font-semibold tabular-nums">
            {fmt(spend.today_usd)}
          </div>
          {hasCap && (
            <>
              <div
                className={cn(
                  "text-[11.5px] tabular-nums",
                  compact ? "mt-1.5" : "mt-2",
                  pctTone(pct)
                )}
              >
                {t("budgetUsage", {
                  pct: pct.toFixed(0),
                  cap: fmt(spend.cap_usd ?? 0),
                })}
              </div>
              <div
                className={cn(
                  "ml-auto h-[5px] overflow-hidden rounded-full bg-muted",
                  compact ? "mt-1 w-[168px]" : "mt-1.5 w-[150px]"
                )}
              >
                <div
                  className={cn("h-full rounded-full", barTone(pct))}
                  style={{ width: `${Math.min(100, pct)}%` }}
                />
              </div>
            </>
          )}
        </div>
      </div>

      <div
        className={cn(
          "-mx-6",
          compact
            ? "mt-1 h-[188px]"
            : "mt-2.5 min-h-[96px] flex-1"
        )}
      >
        <SpendTrendChart
          data={trend}
          height={compact ? 188 : 190}
          locale={locale}
          seriesLabel={t("spend")}
          cumulativeLabel={t("cumulative")}
        />
      </div>
    </div>
  );
}
