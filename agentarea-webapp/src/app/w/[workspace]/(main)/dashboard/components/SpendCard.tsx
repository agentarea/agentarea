import { useLocale, useTranslations } from "next-intl";
import { Wallet } from "lucide-react";
import type {
  AgentSpend,
  DailySpendPoint,
  SpendCard as SpendCardData,
} from "@/api/client";
import { AgentAvatar } from "@/components/AgentAvatar";
import { BoardSectionHeader } from "@/components/board";
import { computeDelta, DeltaBadge } from "@/components/charts/Sparkline";
import { SpendTrendChart } from "@/components/charts/SpendTrendChart";
import Link from "@/components/WorkspaceLink";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

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
  topAgents,
  currency,
  compact = false,
}: {
  spend: SpendCardData;
  trend: DailySpendPoint[];
  topAgents: AgentSpend[];
  currency: string | null;
  compact?: boolean;
}) {
  const t = useTranslations("DashboardPage");
  const locale = useLocale();
  // Money arrives as decimal strings; numbers are only for display and charts.
  const fmt = (v: string) => formatMoney(Number(v), currency, locale);
  const hasCap = spend.cap_usd !== null;
  const pct = spend.pct_of_cap ?? 0;

  const trendPoints = (trend ?? []).map((p) => ({
    date: p.date,
    usd: Number(p.usd),
  }));
  const delta = computeDelta(
    trendPoints.map((p) => p.usd),
    1
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BoardSectionHeader
        icon={<Wallet />}
        color="hsl(var(--foreground))"
        title={t("spend")}
        meta={t("monthToDate")}
      />

      <div
        className={cn("flex items-start gap-3.5", compact ? "mt-1" : "mt-1.5")}
      >
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
          {spend.projected_eom_usd !== null && (
            <div className="mt-1 text-[12.5px] tabular-nums text-muted-foreground">
              {t("projectedEom", { amount: fmt(spend.projected_eom_usd) })}
            </div>
          )}
          {spend.mtd_estimate_usd && Number(spend.mtd_estimate_usd) > 0 && (
            <div className="mt-1 text-[11.5px] tabular-nums text-muted-foreground">
              {t("estimatePart", { amount: fmt(spend.mtd_estimate_usd) })}
            </div>
          )}
        </div>

        <div className={cn("ml-auto text-right", compact ? "pt-0" : "pt-0.5")}>
          <div className="text-[11.5px] text-muted-foreground">
            {t("today")}
          </div>
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
                  cap: fmt(spend.cap_usd ?? "0"),
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
          compact ? "mt-1 h-[150px]" : "mt-2.5 min-h-[96px] flex-1"
        )}
      >
        <SpendTrendChart
          data={trendPoints}
          height={compact ? 150 : 190}
          locale={locale}
          currency={currency}
          seriesLabel={t("spend")}
        />
      </div>

      {topAgents.length > 0 && (
        <div className="mt-3">
          <div className="text-[11.5px] text-muted-foreground">
            {t("topAgents")}
          </div>
          <ul className="mt-1.5 flex flex-col gap-1.5">
            {topAgents.map((a) => {
              const share =
                Number(spend.mtd_usd) > 0
                  ? (Number(a.usd) / Number(spend.mtd_usd)) * 100
                  : 0;
              const name = a.agent_name ? (
                <Link
                  href={`/agents/${a.agent_id}`}
                  className="truncate font-medium hover:underline"
                >
                  {a.agent_name}
                </Link>
              ) : (
                <span className="truncate text-muted-foreground">
                  {t("deletedAgent")}
                </span>
              );
              return (
                <li
                  key={a.agent_id}
                  className="flex min-w-0 items-center gap-2 text-[13px]"
                >
                  <AgentAvatar
                    agent={{ id: a.agent_id, name: a.agent_name }}
                    size="xs"
                  />
                  {name}
                  <span className="ml-auto shrink-0 text-[11.5px] tabular-nums text-muted-foreground">
                    {share.toFixed(0)}%
                  </span>
                  <span className="w-[72px] shrink-0 text-right font-semibold tabular-nums">
                    {fmt(a.usd)}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
