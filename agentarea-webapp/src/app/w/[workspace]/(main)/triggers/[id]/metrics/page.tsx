import { getLocale, getTranslations } from "next-intl/server";
import { CalendarClock, Clock, Gauge, Hash, Wallet } from "lucide-react";
import type { ExecutionMetricsResponse } from "@/api/client/types.gen";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { Stat, StatStrip } from "@/components/Overview/OverviewCard";
import { getTriggerMetrics } from "@/lib/api";
import { getPricingCurrency } from "@/lib/api-dashboard";
import { formatTriggerCost } from "../../components/triggerDisplay";
import { metricsPeriodHours, parseMetricsPeriod } from "./period";

interface Props {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

const seconds = (ms: number) => `${(ms / 1000).toFixed(2)}`;

export default async function TriggerMetricsPage({
  params,
  searchParams,
}: Props) {
  const { id } = await params;
  // The window comes from the subheader's period picker; the overview always
  // shows the whole history.
  const period = parseMetricsPeriod((await searchParams).period);
  const hours = metricsPeriodHours(period);
  const t = await getTranslations("TriggersPage.detail");
  const locale = await getLocale();
  // Never guess a currency: a failed lookup threads through as null (see
  // formatMoney in @/lib/money for how that renders) rather than USD.
  const pricingCurrency = await getPricingCurrency();
  const currency = pricingCurrency.ok ? pricingCurrency.currency : null;
  const fmtCost = (value: number) => formatTriggerCost(value, currency, locale);

  const { data, error } = await getTriggerMetrics(
    id,
    hours !== undefined ? { hours } : undefined
  );

  if (error || !data) {
    return (
      <RetryEmptyState
        title={t("metricsLoadFailed")}
        iconsType="triggers"
        additionAction={{
          label: t("overview"),
          href: `/triggers/${id}`,
        }}
      />
    );
  }
  const metrics = data as ExecutionMetricsResponse;
  const total = metrics.total_executions ?? 0;
  // The API reports percentages, not fractions.
  const successPct = metrics.success_rate ?? 0;
  const failed = metrics.failed_executions ?? 0;
  // The rate leaves out events the trigger's conditions turned away.
  const attempted =
    (metrics.successful_executions ?? 0) +
    failed +
    (metrics.timeout_executions ?? 0);
  const totalCost = metrics.total_cost_usd ?? 0;

  return (
    <div className="bg-muted/20 px-4 pb-11 pt-[18px]">
      {/* Every figure covers the picked window: said once, over the strip,
          rather than as the same tag on each of the four. */}
      <p className="mb-2 flex items-center gap-1.5 px-0.5 text-xs text-muted-foreground">
        <CalendarClock className="h-3.5 w-3.5" />
        {t(`periodLabel.${period}`)}
      </p>
      <StatStrip>
        <Stat
          icon={<Gauge />}
          label={t("successRate")}
          value={attempted > 0 ? successPct.toFixed(0) : "—"}
          unit={attempted > 0 ? "%" : undefined}
          bar={attempted > 0 ? { pct: successPct } : null}
          sub={
            attempted > 0
              ? t("ofRuns", {
                  successful: metrics.successful_executions ?? 0,
                  total: attempted,
                })
              : t("noRuns")
          }
        />
        <Stat
          icon={<Hash />}
          label={t("totalExecutions")}
          value={total}
          bar={null}
          sub={
            total === 0
              ? t("noRuns")
              : failed > 0
                ? t("failedRuns", { count: failed })
                : t("noFailures")
          }
        />
        <Stat
          icon={<Clock />}
          label={t("avgExecutionTime")}
          value={total > 0 ? seconds(metrics.avg_execution_time_ms ?? 0) : "—"}
          unit={total > 0 ? "s" : undefined}
          bar={null}
          sub={
            total > 0
              ? t("durationRange", {
                  min: seconds(metrics.min_execution_time_ms ?? 0),
                  max: seconds(metrics.max_execution_time_ms ?? 0),
                })
              : t("noRuns")
          }
        />
        <Stat
          icon={<Wallet />}
          label={t("spend")}
          value={fmtCost(totalCost)}
          bar={null}
          sub={
            (metrics.costed_executions ?? 0) > 0
              ? t("spendPerRun", { cost: fmtCost(metrics.avg_cost_usd ?? 0) })
              : t("noCostedRuns")
          }
        />
      </StatStrip>
    </div>
  );
}
