import Link from "next/link";
import { useTranslations } from "next-intl";
import { Shield } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import { BoardSectionHeader } from "@/components/board";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { cn } from "@/lib/utils";
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

type Group = { label: string; dot: string; rows: BlockerRow[] };

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
      dot: "bg-amber-500",
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
      dot: "bg-blue-500",
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
      dot: "bg-red-500",
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
      <div className="px-6 pb-3 pt-4">
        <BoardSectionHeader
          icon={<Shield />}
          color="hsl(var(--chart-4))"
          title={t("blockers")}
          pill={total > 0 ? total : undefined}
          meta={total === 0 ? t("healthy") : undefined}
        />
      </div>

      <div className="min-h-0 flex-1 lg:overflow-y-auto">
        {total === 0 ? (
          <div className="px-6 py-8 text-center text-[12px] text-muted-foreground">
            {t("nothingBlocking")}
          </div>
        ) : (
          groups.map((g) => (
            <div key={g.label}>
              <div className="flex h-[34px] items-center gap-2.5 border-b border-t border-border/60 px-6 [background-image:var(--hatch-soft)] lg:sticky lg:top-0 lg:z-[2]">
                <span className={cn("h-2 w-2 shrink-0 rounded-full", g.dot)} />
                <span className="text-[12.5px] font-semibold text-foreground">
                  {g.label}
                </span>
                <span className="flex-1" />
                <span className="rounded-full bg-muted px-2 font-mono text-[11.5px] font-medium leading-[18px] text-muted-foreground">
                  {g.rows.length}
                </span>
              </div>

              {g.rows.map((r) => (
                <Link key={r.key} href={r.href} className="block">
                  <InteractiveListRow
                    className="px-6 py-2.5"
                    dividerClassName="border-b border-border/60"
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
            </div>
          ))
        )}
      </div>
    </div>
  );
}
