import { useLocale, useTranslations } from "next-intl";
import { Wallet } from "lucide-react";
import type { DailySpendPoint, SpendCard } from "@/api/client";
import { BoardSectionHeader } from "@/components/board";
import { SpendTrendChart } from "@/components/charts/SpendTrendChart";
import { formatMoney } from "@/lib/money";

/** This month's spend: the total, today, the projection and the daily chart. */
export function BudgetSpend({
  spend,
  trend,
  currency,
}: {
  spend: SpendCard;
  trend: DailySpendPoint[];
  currency: string | null;
}) {
  const t = useTranslations("BudgetsPage");
  const tDash = useTranslations("DashboardPage");
  const locale = useLocale();
  const fmt = (v: string) => formatMoney(Number(v), currency, locale);

  const points = trend.map((p) => ({ date: p.date, usd: Number(p.usd) }));

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BoardSectionHeader
        icon={<Wallet />}
        color="hsl(var(--foreground))"
        title={tDash("spend")}
        meta={tDash("monthToDate")}
      />

      <div className="mt-2 text-[28px] font-semibold leading-none tracking-[-0.03em] tabular-nums">
        {fmt(spend.mtd_usd)}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] tabular-nums text-muted-foreground">
        <span>{t("todayAmount", { amount: fmt(spend.today_usd) })}</span>
        {spend.projected_eom_usd !== null && (
          <span>
            {tDash("projectedEom", { amount: fmt(spend.projected_eom_usd) })}
          </span>
        )}
        {spend.mtd_estimate_usd && Number(spend.mtd_estimate_usd) > 0 && (
          <span>
            {tDash("estimatePart", { amount: fmt(spend.mtd_estimate_usd) })}
          </span>
        )}
      </div>

      <div className="-mx-8 mt-3 h-[190px]">
        <SpendTrendChart
          data={points}
          height={190}
          locale={locale}
          currency={currency}
          seriesLabel={tDash("spend")}
        />
      </div>
    </div>
  );
}
