import { getTranslations } from "next-intl/server";
import { SpendCard } from "@/app/(main)/dashboard/components/SpendCard";
import EmptyState from "@/components/EmptyState";
import { getDashboard, getWorkspaceSettings } from "@/lib/api-dashboard";
import { BudgetCapPanel } from "./BudgetCapPanel";
import { BudgetsBoard } from "./BudgetsBoard";
import { MonthOutlook } from "./MonthOutlook";

export async function BudgetsData() {
  let data: Awaited<ReturnType<typeof getDashboard>> | null = null;
  let settings: Awaited<ReturnType<typeof getWorkspaceSettings>> | null = null;
  let error: string | null = null;
  let settingsError: string | null = null;

  try {
    const [dashboardResult, settingsResult] = await Promise.allSettled([
      getDashboard(),
      getWorkspaceSettings(),
    ]);

    if (dashboardResult.status === "fulfilled") {
      data = dashboardResult.value;
    } else {
      throw dashboardResult.reason;
    }

    if (settingsResult.status === "fulfilled") {
      settings = settingsResult.value;
    } else {
      settingsError =
        settingsResult.reason instanceof Error
          ? settingsResult.reason.message
          : "Failed to load workspace settings";
    }
  } catch (e) {
    console.error("Failed to load budgets data:", e);
    error = e instanceof Error ? e.message : "Failed to load budget data";
  }

  if (error) {
    const t = await getTranslations("BudgetsPage");
    return (
      <div className="p-6">
        <EmptyState
          title={t("couldntLoadTitle")}
          description={error}
          iconsType="payments"
        />
      </div>
    );
  }

  if (!data) return null;

  const cap = settings?.monthly_cap_usd ?? data.spend.cap_usd;

  return (
    <BudgetsBoard
      spend={<SpendCard spend={data.spend} trend={data.daily_spend} compact />}
      outlook={
        <MonthOutlook
          today={data.spend.today_usd}
          projected={data.spend.projected_eom_usd}
          cap={cap}
          runRateDays={data.daily_spend?.length ?? 30}
        />
      }
      capCard={
        <BudgetCapPanel
          initialCap={cap}
          mtdSpend={data.spend.mtd_usd}
          settingsError={settingsError}
        />
      }
    />
  );
}
