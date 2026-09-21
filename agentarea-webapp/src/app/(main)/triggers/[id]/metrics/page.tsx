import { getTranslations } from "next-intl/server";
import { Clock, Gauge, Hash, Wallet } from "lucide-react";
import type { ExecutionMetricsResponse } from "@/api/client/types.gen";
import { Stat, StatStrip } from "@/components/Overview/OverviewCard";
import { getTriggerMetrics } from "@/lib/api";
import { formatTriggerCost as fmtUsd } from "../../components/triggerDisplay";

interface Props {
  params: Promise<{ id: string }>;
}

/** The window this tab reports on. The overview shows the whole history. */
const WINDOW_HOURS = 24;

const seconds = (ms: number) => `${(ms / 1000).toFixed(2)}`;

export default async function TriggerMetricsPage({ params }: Props) {
  const { id } = await params;
  const t = await getTranslations("TriggersPage.detail");

  const { data, error } = await getTriggerMetrics(id, { hours: WINDOW_HOURS });

  if (error || !data) {
    return (
      <div className="flex h-64 items-center justify-center text-destructive">
        {t("metricsLoadFailed")}
      </div>
    );
  }

  const metrics = data as ExecutionMetricsResponse;
  const total = metrics.total_executions ?? 0;
  // The API reports percentages, not fractions.
  const successPct = metrics.success_rate ?? 0;
  const failed = metrics.failed_executions ?? 0;
  const totalCost = metrics.total_cost_usd ?? 0;

  return (
    <div className="bg-muted/20 px-4 pb-11 pt-[18px]">
      <StatStrip>
        <Stat
          icon={<Gauge />}
          label={t("successRate")}
          value={total > 0 ? successPct.toFixed(0) : "—"}
          unit={total > 0 ? "%" : undefined}
          bar={total > 0 ? { pct: successPct } : null}
          sub={
            total > 0
              ? t("ofRuns", {
                  successful: metrics.successful_executions ?? 0,
                  total,
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
            failed > 0
              ? t("failedRuns", { count: failed })
              : t("periodHours", { hours: metrics.period_hours ?? WINDOW_HOURS })
          }
          subTone={failed > 0 ? "down" : "muted"}
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
          value={fmtUsd(totalCost)}
          bar={null}
          sub={
            (metrics.costed_executions ?? 0) > 0
              ? t("spendPerRun", { cost: fmtUsd(metrics.avg_cost_usd ?? 0) })
              : t("noCostedRuns")
          }
        />
      </StatStrip>
    </div>
  );
}
