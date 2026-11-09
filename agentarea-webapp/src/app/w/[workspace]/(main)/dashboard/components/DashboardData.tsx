import { getTranslations } from "next-intl/server";
import { BalanceSection } from "@/components/BalanceSection";
import { BoardColumns } from "@/components/board";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { getDashboard, getPricingCurrency } from "@/lib/api-dashboard";
import { apiErrorMessage } from "@/lib/api-errors";
import { ActivityPanel } from "./ActivityPanel";
import { AttentionPanel } from "./AttentionPanel";
import { ScheduleCalendar } from "./ScheduleCalendar";
import { SpendCard } from "./SpendCard";
import { WalletAlerts } from "./WalletAlerts";

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
    <BoardColumns
      left={[
        <AttentionPanel
          key="attention"
          blockers={data.blockers}
          health={data.health}
        />,
        <ScheduleCalendar key="schedule" schedule={data.schedule} />,
      ]}
      right={[
        <div key="money">
          <WalletAlerts
            wallets={data.blockers.wallet_exhausted}
            currency={currency}
          />
          <BalanceSection />
          <div className="flex flex-col px-6 pb-4 pt-3.5">
            <SpendCard
              spend={data.spend}
              trend={data.daily_spend}
              topAgents={data.top_agents}
              currency={currency}
              compact
            />
          </div>
        </div>,
        <ActivityPanel
          key="activity"
          active={data.active_tasks}
          recent={data.recent_tasks}
          currency={currency}
        />,
      ]}
    />
  );
}
