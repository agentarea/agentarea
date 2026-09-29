import { getTranslations } from "next-intl/server";
import { BoardGrid } from "@/components/board";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { getDashboard, getPricingCurrency } from "@/lib/api-dashboard";
import { apiErrorMessage } from "@/lib/api-errors";
import { ActivityStrip } from "./ActivityStrip";
import { AgentRows } from "./AgentRows";
import { BlockersPanel } from "./BlockersPanel";
import { SpendCard } from "./SpendCard";

export async function DashboardData() {
  const [result, pricing] = await Promise.all([
    getDashboard().catch((e: unknown) => {
      console.error("Failed to load dashboard", e);
      return { data: undefined, error: e, status: undefined };
    }),
    getPricingCurrency(),
  ]);
  const currency = pricing.ok ? pricing.currency : null;
  const data = result.data;

  if (result.error || !data) {
    const t = await getTranslations("DashboardPage");
    return (
      <div className="p-6">
        <RetryEmptyState
          title={t("couldntLoadTitle")}
          description={apiErrorMessage(result, t("couldntLoadTitle"))}
          iconsType="tasks"
        />
      </div>
    );
  }

  return (
    <BoardGrid
      topLeft={
        <SpendCard
          spend={data.spend}
          trend={data.daily_spend}
          currency={currency}
        />
      }
      topRight={<ActivityStrip data={data.daily_tasks} />}
      bottomLeft={<AgentRows agents={data.agents} currency={currency} />}
      bottomRight={
        <BlockersPanel blockers={data.blockers} currency={currency} />
      }
    />
  );
}
