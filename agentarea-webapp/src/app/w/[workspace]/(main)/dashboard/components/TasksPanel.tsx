import { useLocale, useTranslations } from "next-intl";
import { ArrowUpRight, ListChecks } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import { BoardSectionHeader } from "@/components/board";
import EmptyState from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { CollapsibleGroup } from "@/components/ui/group-header";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { StatusIndicator } from "@/components/ui/status-indicator";
import Link from "@/components/WorkspaceLink";
import type { DashboardTask } from "@/lib/api-dashboard";
import { formatMoney } from "@/lib/money";
import { getTaskStatusPresentation } from "@/lib/status";
import { formatRelTime } from "./relTime";

function Dot() {
  return (
    <span className="h-[2.5px] w-[2.5px] shrink-0 rounded-full bg-muted-foreground/60" />
  );
}

export function TasksPanel({
  active,
  recent,
  currency,
}: {
  active: DashboardTask[];
  recent: DashboardTask[];
  currency: string | null;
}) {
  const t = useTranslations("DashboardPage");
  const tStatus = useTranslations("TasksPage.status");
  const locale = useLocale();

  const row = (task: DashboardTask, when: string | null) => {
    const status = getTaskStatusPresentation(task.status);
    const label = status.labelKey ? tStatus(status.labelKey) : status.label;
    return (
      <Link key={task.task_id} href={`/tasks/${task.task_id}`} className="block">
        <InteractiveListRow
          className="px-6 py-2.5"
          contentClassName="items-start"
          start={
            <StatusIndicator
              kind={status.kind}
              size="sm"
              aria-label={label}
              title={label}
              className="mt-[3px]"
            />
          }
        >
          <div className="flex min-w-0 flex-col gap-1.5">
            <span className="truncate text-[13.5px] font-medium text-foreground">
              {task.title || t("untitledTask")}
            </span>
            <span className="flex min-w-0 items-center gap-2 text-[12px] text-muted-foreground">
              {task.agent_name && (
                <>
                  <AgentAvatar
                    agent={{ id: task.agent_id, name: task.agent_name }}
                    size="xs"
                  />
                  <span className="truncate font-medium">
                    {task.agent_name}
                  </span>
                  <Dot />
                </>
              )}
              <span className="shrink-0 font-mono">
                {t("timeAgo", { time: formatRelTime(when, t) })}
              </span>
              {task.cost_usd !== null && (
                <>
                  <Dot />
                  <span className="shrink-0 font-mono">
                    {formatMoney(task.cost_usd, currency, locale)}
                  </span>
                </>
              )}
            </span>
          </div>
        </InteractiveListRow>
      </Link>
    );
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-zinc-200 px-6 pb-3 pt-4 dark:border-zinc-700">
        <BoardSectionHeader
          icon={<ListChecks />}
          color="hsl(var(--foreground))"
          title={t("tasks")}
          meta={
            <Button
              asChild
              variant="ghost"
              size="xs"
              className="text-muted-foreground"
            >
              <Link href="/tasks">
                {t("allTasks")}
                <ArrowUpRight />
              </Link>
            </Button>
          }
        />
      </div>

      <div className="min-h-0 flex-1 lg:overflow-y-auto">
        {active.length === 0 && recent.length === 0 ? (
          <div className="flex min-h-0 flex-1 flex-col justify-center">
            <EmptyState
              iconsType="tasks"
              accentClassName="text-primary"
              title={t("noTasks")}
              description={t("noTasksHint")}
              className="border-0 bg-transparent p-6 shadow-none hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent"
            />
          </div>
        ) : (
          <>
            {active.length > 0 && (
              <CollapsibleGroup
                label={t("runningNow")}
                count={active.length}
                icon={
                  <StatusIndicator
                    kind="running"
                    size="sm"
                    aria-label={t("runningNow")}
                  />
                }
                sticky={false}
                headerClassName="px-6 lg:sticky lg:top-0 lg:z-10"
              >
                {active.map((task) => row(task, task.started_at))}
              </CollapsibleGroup>
            )}
            {recent.length > 0 && (
              <CollapsibleGroup
                label={t("recentlyFinished")}
                count={recent.length}
                icon={
                  <StatusIndicator
                    kind="done"
                    size="sm"
                    aria-label={t("recentlyFinished")}
                  />
                }
                sticky={false}
                headerClassName="px-6 lg:sticky lg:top-0 lg:z-10"
              >
                {recent.map((task) => row(task, task.finished_at))}
              </CollapsibleGroup>
            )}
          </>
        )}
      </div>
    </div>
  );
}
