import { getTranslations } from "next-intl/server";
import { BalanceSection } from "@/components/BalanceSection";
import { BoardColumns } from "@/components/board";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import {
  getDashboard,
  getPricingCurrency,
  getWorkspaceSettings,
} from "@/lib/api-dashboard";
import { apiErrorMessage } from "@/lib/api-errors";
import { BudgetAgents } from "./BudgetAgents";
import { BudgetCap } from "./BudgetCap";
import { BudgetSpend } from "./BudgetSpend";
import { RuntimeUsageStats } from "./RuntimeUsageStats";

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

  // Money arrives as decimal strings; the budget views take numbers.
  const amount = (v: string | null) => (v == null ? null : Number(v));
  const cap = amount(settings?.monthly_cap_usd ?? data.spend.cap_usd);
  const currency = pricing.ok ? pricing.currency : null;

  return (
    <BoardColumns
      leftFraction={0.6}
      left={[
        <div key="spend" className="px-8 pb-6 pt-5">
          <BudgetSpend
            spend={data.spend}
            trend={data.daily_spend}
            currency={currency}
          />
        </div>,
        ...(data.usage
          ? [
              <div key="usage" className="px-8 pb-6 pt-5">
                <RuntimeUsageStats usage={data.usage} />
              </div>,
            ]
          : []),
        <div key="agents" className="px-8 pb-6 pt-5">
          <BudgetAgents
            agents={data.top_agents}
            total={Number(data.spend.mtd_usd)}
            currency={currency}
          />
        </div>,
      ]}
      right={[
        <div key="money">
          <BalanceSection />
          <div className="px-8 pb-6 pt-5">
            <BudgetCap
              initialCap={cap}
              mtdSpend={Number(data.spend.mtd_usd)}
              projected={amount(data.spend.projected_eom_usd)}
              currency={currency}
              settingsError={settingsError}
            />
          </div>
        </div>,
      ]}
    />
  );
}
