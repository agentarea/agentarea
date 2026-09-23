import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import EmptyState from "@/components/EmptyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import TasksList from "@/app/(main)/tasks/components/TasksList";
import type { TriggerCatalogEntry } from "@/app/(main)/triggers/components/triggerDisplay";
import {
  getAgent,
  listAgentTasks,
  listTriggerCatalog,
  resolvePrincipals,
  type Agent,
  type TaskWithAgent,
} from "@/lib/api";
import { getTaskSource } from "@/lib/taskSource";
import TasksSkeleton from "@/app/(main)/tasks/components/TasksSkeleton";

export const metadata: Metadata = {
  title: "Agent Tasks",
};

interface Props {
  params: Promise<{ id: string }>;
}

/**
 * The agent's runs, in the same table as /tasks. The columns are what the
 * listing is for -- status, source, cost, when -- and a card grid could show
 * none of them. The agent column is dropped: every row here is this agent.
 */
async function AgentTasksData({ agentId }: { agentId: string }) {
  const t = await getTranslations("TasksPage");

  let tasks: TaskWithAgent[] = [];
  let catalog: TriggerCatalogEntry[] = [];
  let error: string | null = null;

  try {
    const [{ data: tasksData, error: tasksError }, catalogResponse] =
      await Promise.all([listAgentTasks(agentId), listTriggerCatalog()]);
    if (tasksError) {
      error = t("error.loadFailedDescription");
    } else {
      tasks = (tasksData ?? []) as TaskWithAgent[];
    }
    catalog = (catalogResponse.data ?? []) as TriggerCatalogEntry[];
  } catch {
    error = t("error.loadFailedDescription");
  }

  // Checked before the empty branch: a failed load also leaves the list empty,
  // and reporting that as "no tasks yet" would hide every backend failure.
  if (error) {
    return (
      <RetryEmptyState
        title={t("error.loadFailed")}
        description={error}
        iconsType="tasks"
      />
    );
  }

  if (tasks.length === 0) {
    return (
      <EmptyState
        title={t("noTasks")}
        description={t("noTasksDescription")}
        iconsType="tasks"
        action={{ label: t("startTaskAction"), href: `/agents/${agentId}/new-task` }}
      />
    );
  }

  // One batch for both principals a row can name: the task's own creator, and
  // whatever its source points at (for a delegated task, the delegating agent).
  const principals = await resolvePrincipals([
    ...new Set(
      tasks
        .flatMap((task) => [
          task.created_by,
          getTaskSource(task.parameters ?? undefined).principalId,
        ])
        .filter((id): id is string => Boolean(id))
    ),
  ]);
  const principalNames = Object.fromEntries(
    (principals.data ?? [])
      .filter((principal) => principal.display_name)
      .map((principal) => [principal.id, principal.display_name as string])
  );

  return (
    <TasksList
      initialTasks={tasks}
      viewMode="table"
      catalog={catalog}
      principalNames={principalNames}
      showAgent={false}
    />
  );
}

export default async function AgentTasksPage({ params }: Props) {
  const { id } = await params;
  const t = await getTranslations("TasksPage");

  const agentRes = await getAgent(id);
  const agent = agentRes.data as Agent | undefined;
  if (!agent) notFound();

  // Same columns the table renders, minus the agent one it drops here.
  const skeletonColumns = [
    { header: t("statusLabel"), barClassName: "h-5 w-20 rounded-full" },
    { header: t("description"), barClassName: "h-4 w-48" },
    { header: t("source"), barClassName: "h-4 w-24" },
    { header: t("cost"), barClassName: "h-4 w-12" },
    { header: t("created"), barClassName: "h-8 w-24" },
  ];

  return (
    <div className="h-full overflow-auto px-4 py-5">
      <Suspense
        fallback={<TasksSkeleton viewMode="table" columns={skeletonColumns} />}
      >
        <AgentTasksData agentId={agent.id} />
      </Suspense>
    </div>
  );
}
