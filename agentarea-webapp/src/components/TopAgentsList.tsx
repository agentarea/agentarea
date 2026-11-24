import { useLocale, useTranslations } from "next-intl";
import type { AgentSpend } from "@/api/client";
import { AgentAvatar } from "@/components/AgentAvatar";
import Link from "@/components/WorkspaceLink";
import { formatMoney } from "@/lib/money";

/** The agents that spent the most this month, with their share of the total. */
export function TopAgentsList({
  agents,
  total,
  currency,
}: {
  agents: AgentSpend[];
  /** Month-to-date spend of the workspace, the base of each share. */
  total: number;
  currency: string | null;
}) {
  const t = useTranslations("DashboardPage");
  const locale = useLocale();

  return (
    <ul className="flex flex-col gap-1.5">
      {agents.map((a) => {
        const share = total > 0 ? (Number(a.usd) / total) * 100 : 0;
        return (
          <li
            key={a.agent_id}
            className="flex min-w-0 items-center gap-2 text-[13px]"
          >
            <AgentAvatar
              agent={{ id: a.agent_id, name: a.agent_name }}
              size="xs"
            />
            {a.agent_name ? (
              <Link
                href={`/agents/${a.agent_id}`}
                className="truncate font-medium hover:underline"
              >
                {a.agent_name}
              </Link>
            ) : (
              <span className="truncate text-muted-foreground">
                {t("deletedAgent")}
              </span>
            )}
            <span className="ml-auto shrink-0 text-[11.5px] tabular-nums text-muted-foreground">
              {share.toFixed(0)}%
            </span>
            <span className="w-[72px] shrink-0 text-right font-semibold tabular-nums">
              {formatMoney(Number(a.usd), currency, locale)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
