import { getTranslations } from "next-intl/server";
import { SpendCard } from "@/app/w/[workspace]/(main)/dashboard/components/SpendCard";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import {
  getDashboard,
  getPricingCurrency,
  getWorkspaceSettings,
} from "@/lib/api-dashboard";
import { apiErrorMessage } from "@/lib/api-errors";
import { BudgetCapPanel } from "./BudgetCapPanel";
import { BudgetsBoard } from "./BudgetsBoard";
import { MonthOutlook } from "./MonthOutlook";

export async function BudgetsData() {
  const failed = (label: string) => (e: unknown) => {
    console.error(label, e);
    return { data: undefined, error: e, status: undefined };
  };
  const [dashboardResult, settingsResult, pricing, t] = await Promise.all([
    getDashboard().catch(failed("Failed to load budgets data")),
    getWorkspaceSettings().catch(failed("Failed to load workspace settings")),
    getPricingCurrency(),
    getTranslations("BudgetsPage"),
  ]);
  const data = dashboardResult.data;

  if (dashboardResult.error || !data) {
    return (
      <div className="p-6">
        <RetryEmptyState
          title={t("couldntLoadTitle")}
          description={apiErrorMessage(dashboardResult, t("couldntLoadTitle"))}
          iconsType="payments"
        />
      </div>
    );
  }

  const settings = settingsResult.data;
  const settingsError =
    settingsResult.error || !settings
      ? apiErrorMessage(settingsResult, t("settingsLoadFailed"))
      : null;

  const cap = settings?.monthly_cap_usd ?? data.spend.cap_usd;
  const currency = pricing.ok ? pricing.currency : null;

  return (
    <BudgetsBoard
      spend={
        <SpendCard
          spend={data.spend}
          trend={data.daily_spend}
          currency={currency}
          compact
        />
      }
      outlook={
        <MonthOutlook
          today={data.spend.today_usd}
          projected={data.spend.projected_eom_usd}
          cap={cap}
          runRateDays={data.daily_spend?.length ?? 30}
          currency={currency}
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
