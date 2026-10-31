import { useLocale, useTranslations } from "next-intl";
import { ArrowUpRight, History } from "lucide-react";
import type { DashboardTask } from "@/api/client";
import { BoardSectionHeader } from "@/components/board";
import EmptyState from "@/components/EmptyState";
import { TaskStatus } from "@/components/TaskStatus";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";
import { formatMoney } from "@/lib/money";
import { RowGroup, type Row } from "./DashboardRow";
import { formatRelTime } from "./relTime";

/** The work in flight and the work just done. */
export function ActivityPanel({
  active,
  recent,
  currency,
}: {
  active: DashboardTask[];
  recent: DashboardTask[];
  currency: string | null;
}) {
  const t = useTranslations("DashboardPage");
  const locale = useLocale();

  const taskRow = (task: DashboardTask, when: string | null): Row => ({
    key: task.task_id,
    href: `/tasks/${task.task_id}`,
    status: <TaskStatus status={task.status} size="sm" caption="never" />,
    title: task.title || t("untitledTask"),
    agent: task.agent_name
      ? { id: task.agent_id, name: task.agent_name }
      : null,
    time: formatRelTime(when, t),
    amount:
      task.cost_usd !== null
        ? formatMoney(Number(task.cost_usd), currency, locale)
        : null,
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-zinc-200 px-6 pb-3 pt-4 dark:border-zinc-700">
        <BoardSectionHeader
          icon={<History />}
          color="hsl(var(--foreground))"
          title={t("activity")}
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

      {active.length === 0 && recent.length === 0 ? (
        <EmptyState
          iconsType="tasks"
          accentClassName="text-primary"
          title={t("noTasks")}
          description={t("noTasksHint")}
          className="border-0 bg-transparent p-6 shadow-none hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent"
        />
      ) : (
        <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          <RowGroup
            label={t("runningNow")}
            kind="running"
            rows={active.map((task) => taskRow(task, task.started_at))}
          />
          <RowGroup
            label={t("recentlyFinished")}
            kind="done"
            rows={recent.map((task) => taskRow(task, task.finished_at))}
          />
        </div>
      )}
    </div>
  );
}
