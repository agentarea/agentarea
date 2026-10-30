import { getTranslations } from "next-intl/server";
import { BalanceSection } from "@/components/BalanceSection";
import { BoardGrid } from "@/components/board";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { getDashboard, getPricingCurrency } from "@/lib/api-dashboard";
import { apiErrorMessage } from "@/lib/api-errors";
import { BlockersPanel } from "./BlockersPanel";
import { ScheduleCalendar } from "./ScheduleCalendar";
import { SpendCard } from "./SpendCard";
import { TasksPanel } from "./TasksPanel";

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
      topLeft={<BlockersPanel blockers={data.blockers} currency={currency} />}
      topLeftPadded={false}
      topRight={
        <>
          <BalanceSection />
          <div className="flex min-h-0 flex-1 flex-col px-6 pb-4 pt-3.5">
            <SpendCard
              spend={data.spend}
              trend={data.daily_spend}
              topAgents={data.top_agents}
              currency={currency}
              compact
            />
          </div>
        </>
      }
      topRightPadded={false}
      bottomLeft={<ScheduleCalendar schedule={data.schedule} />}
      bottomRight={
        <TasksPanel
          active={data.active_tasks}
          recent={data.recent_tasks}
          currency={currency}
        />
      }
    />
  );
}
