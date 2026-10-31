import { useLocale, useTranslations } from "next-intl";
import type { WalletExhaustedBlocker } from "@/api/client";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { formatMoney } from "@/lib/money";
import { DashboardRow } from "./DashboardRow";

/** Agents whose own budget ran out, one row each; nothing when none did. */
export function WalletAlerts({
  wallets,
  currency,
}: {
  wallets: WalletExhaustedBlocker[];
  currency: string | null;
}) {
  const t = useTranslations("DashboardPage");
  const locale = useLocale();

  if (wallets.length === 0) return null;

  return (
    <div>
      {wallets.map((w) => {
        const label = t("budgetExhausted", {
          amount: formatMoney(Number(w.budget_usd), currency, locale),
          period: w.period,
        });
        return (
          <DashboardRow
            key={w.agent_id}
            href={`/agents/${w.agent_id}`}
            status={
              <StatusIndicator kind="attention" size="sm" aria-label={label} />
            }
            title={label}
            agent={w.agent_name ? { id: w.agent_id, name: w.agent_name } : null}
          />
        );
      })}
    </div>
  );
}
