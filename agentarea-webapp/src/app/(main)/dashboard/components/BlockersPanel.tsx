import Link from "next/link";
import { useTranslations } from "next-intl";
import { Shield } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import EmptyState from "@/components/EmptyState";
import { BoardSectionHeader } from "@/components/board";
import { CollapsibleGroup } from "@/components/ui/group-header";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import type { DashboardData } from "@/lib/api-dashboard";
import { formatRelTime } from "./relTime";

type BlockerRow = {
  key: string;
  question: string;
  agentId: string;
  agentName: string;
  ago: string;
  href: string;
};

type Group = { label: string; color: string; rows: BlockerRow[] };

export function BlockersPanel({
  blockers,
}: {
  blockers: DashboardData["blockers"];
}) {
  const t = useTranslations("DashboardPage");
  const ago = (iso: string | null) =>
    t("timeAgo", { time: formatRelTime(iso, t) });

  const groups: Group[] = [
    {
      label: t("awaitingInput"),
      color: "var(--status-warning)",
      rows: blockers.hitl.map((b) => ({
        key: b.task_id,
        question: b.description,
        agentId: b.agent_id,
        agentName: b.agent_name,
        ago: ago(b.created_at),
        href: `/tasks/${b.task_id}`,
      })),
    },
    {
      label: t("walletExhausted"),
      color: "var(--status-info)",
      rows: blockers.wallet_exhausted.map((b) => ({
        key: b.agent_id,
        question: t("budgetExhausted", {
          amount: `$${b.budget_usd.toFixed(2)}`,
          period: b.period,
        }),
        agentId: b.agent_id,
        agentName: b.agent_name,
        ago: b.period,
        href: `/agents/${b.agent_id}`,
      })),
    },
    {
      label: t("failed24h"),
      color: "var(--status-danger)",
      rows: blockers.failed_24h.map((b) => ({
        key: b.task_id,
        question: b.error?.split("\n")[0] || t("taskFailed"),
        agentId: b.agent_id,
        agentName: b.agent_name,
        ago: ago(b.occurred_at),
        href: `/tasks/${b.task_id}`,
      })),
    },
  ].filter((g) => g.rows.length > 0);

  const total = groups.reduce((n, g) => n + g.rows.length, 0);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-zinc-200 px-6 pb-3 pt-4 dark:border-zinc-700">
        <BoardSectionHeader
          icon={<Shield />}
          color="var(--amber)"
          title={t("blockers")}
          pill={total > 0 ? total : undefined}
        />
      </div>

      <div className="min-h-0 flex-1 lg:overflow-y-auto">
        {total === 0 ? (
          <div className="flex min-h-0 flex-1 flex-col justify-center">
            <EmptyState
              iconsType="healthy"
              accentClassName="text-emerald-500"
              title={t("nothingBlocking")}
              description={t("allClearHint")}
              className="border-0 bg-transparent p-6 shadow-none hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent"
            />
          </div>
        ) : (
          groups.map((g) => (
            <CollapsibleGroup
              key={g.label}
              label={g.label}
              count={g.rows.length}
              color={g.color}
              sticky={false}
              headerClassName="px-6 lg:sticky lg:top-0 lg:z-[2]"
            >
              {g.rows.map((r) => (
                <Link key={r.key} href={r.href} className="block">
                  <InteractiveListRow
                    className="px-6 py-2.5"
                    contentClassName="items-start"
                  >
                    <div className="flex min-w-0 flex-col gap-1.5">
                      <span className="truncate text-[13.5px] font-medium text-foreground">
                        {r.question}
                      </span>
                      <span className="flex min-w-0 items-center gap-2 text-[12px] text-muted-foreground">
                        <AgentAvatar
                          agent={{ id: r.agentId, name: r.agentName }}
                          size="xs"
                        />
                        <span className="truncate font-medium">{r.agentName}</span>
                        <span className="h-[2.5px] w-[2.5px] shrink-0 rounded-full bg-muted-foreground/60" />
                        <span className="shrink-0 font-mono">{r.ago}</span>
                      </span>
                    </div>
                  </InteractiveListRow>
                </Link>
              ))}
            </CollapsibleGroup>
          ))
        )}
      </div>
    </div>
  );
}
