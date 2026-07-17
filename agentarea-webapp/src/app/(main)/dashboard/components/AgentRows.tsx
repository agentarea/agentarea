import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowUpRight, Bot } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import EmptyState from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { BoardSectionHeader } from "@/components/board";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { cn } from "@/lib/utils";
import type { DashboardAgentRow } from "@/lib/api-dashboard";
import { formatRelTime } from "./relTime";

const fmt = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

function inferStatus(
  row: DashboardAgentRow
): "idle" | "running" | "error" | null {
  if (!row.last_activity_at) return null;
  const lastMins =
    (Date.now() - new Date(row.last_activity_at).getTime()) / 60000;
  if (row.tasks_failed_today > 0 && lastMins < 60) return "error";
  if (lastMins < 5) return "running";
  return "idle";
}

function Dot() {
  return <span className="h-[2.5px] w-[2.5px] shrink-0 rounded-full bg-muted-foreground/60" />;
}

export function AgentRows({ agents }: { agents: DashboardAgentRow[] }) {
  const t = useTranslations("DashboardPage");

  const stats = (a: DashboardAgentRow, className?: string) => (
    <span
      className={cn(
        "flex items-center gap-2 text-[12px] text-muted-foreground",
        className
      )}
    >
      <span>{t("statDone", { count: a.tasks_done_today })}</span>
      <Dot />
      <span
        className={cn(
          a.tasks_failed_today > 0 &&
            "font-semibold text-red-500 dark:text-red-400"
        )}
      >
        {t("statFailed", { count: a.tasks_failed_today })}
      </span>
      <Dot />
      <span className="font-mono font-medium text-foreground/80">
        {t("statMtd", { amount: fmt(a.cost_mtd_usd) })}
      </span>
    </span>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-zinc-200 px-6 pb-3 pt-4 dark:border-zinc-700">
        <BoardSectionHeader
          icon={<Bot />}
          color="hsl(var(--primary))"
          title={t("agents")}
          pill={t("agentsActive", { count: agents.length })}
          meta={
            <Button asChild variant="ghost" size="xs" className="text-muted-foreground">
              <Link href="/agents">
                {t("viewAllAgents")}
                <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          }
        />
      </div>

      {agents.length === 0 ? (
        <div className="min-h-0 flex-1 lg:overflow-y-auto">
          <div className="flex min-h-0 flex-1 flex-col justify-center">
            <EmptyState
              iconsType="agent"
              accentClassName="text-primary"
              title={t("noAgents")}
              description={t("noAgentsHint")}
              additionAction={{ label: t("createFirstAgent"), href: "/agents" }}
              className="border-0 bg-transparent p-6 shadow-none hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent"
            />
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 lg:overflow-y-auto">
          {agents.map((a) => (
            <Link key={a.agent_id} href={`/agents/${a.agent_id}`} className="block">
              <InteractiveListRow
                showIndicator={false}
                className="px-6 py-2.5"
                start={
                  <AgentAvatar
                    agent={{ id: a.agent_id, name: a.name }}
                    size="sm"
                    status={inferStatus(a)}
                  />
                }
                contentClassName="items-center"
                end={
                  <>
                    {stats(a, "hidden lg:flex")}
                    <ArrowUpRight className="h-4 w-4 -translate-x-0.5 text-primary opacity-0 transition duration-150 group-hover:translate-x-0 group-hover:opacity-100" />
                  </>
                }
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[13.5px] font-medium text-foreground">
                      {a.name}
                    </span>
                    <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                      {formatRelTime(a.last_activity_at, t)}
                    </span>
                  </div>
                  {stats(a, "mt-0.5 lg:hidden")}
                </div>
              </InteractiveListRow>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
