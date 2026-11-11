import { useTranslations } from "next-intl";
import type { AgentSpend } from "@/api/client";
import { BoardSectionHeader } from "@/components/board";
import { TopAgentsList } from "@/components/TopAgentsList";
import { EntityIcon } from "@/lib/entity-icons";

/** Which agents the month's spend went to. */
export function BudgetAgents({
  agents,
  total,
  currency,
}: {
  agents: AgentSpend[];
  total: number;
  currency: string | null;
}) {
  const t = useTranslations("BudgetsPage");
  const tDash = useTranslations("DashboardPage");

  return (
    <div className="flex flex-col gap-3">
      <BoardSectionHeader
        icon={<EntityIcon kind="agent" />}
        color="hsl(var(--foreground))"
        title={t("agentsTitle")}
        meta={tDash("monthToDate")}
      />
      {agents.length > 0 ? (
        <TopAgentsList agents={agents} total={total} currency={currency} />
      ) : (
        <p className="text-[13px] text-muted-foreground">{t("agentsEmpty")}</p>
      )}
    </div>
  );
}
