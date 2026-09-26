import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import {
  getAllTasks,
  listTriggerCatalog,
  resolvePrincipals,
  type TaskWithAgent,
} from "@/lib/api";
import type { TriggerCatalogEntry } from "@/app/w/[workspace]/(main)/triggers/components/triggerDisplay";
import { pageHref, pageWindow, takePage } from "@/lib/offsetPage";
import { getTaskSource } from "@/lib/taskSource";
import type { TaskStatusValue } from "@/lib/taskStatusFilter";
import TasksList from "./TasksList";
import TasksPagination from "./TasksPagination";

const TASKS_PAGE_SIZE = 50;

interface TasksDataProps {
  searchQuery?: string;
  /** tasks.created_by to narrow the list to, from the "Started by" cell's link. */
  creator?: string;
  statuses: TaskStatusValue[];
  page: number;
  searchParams: Record<string, string | string[] | undefined>;
  viewMode?: string;
}

export async function TasksData({
  searchQuery = "",
  creator = "",
  statuses,
  page,
  searchParams,
  viewMode = "table",
}: TasksDataProps) {
  const t = await getTranslations("TasksPage");
  const tCommon = await getTranslations("Common");

  let tasks: TaskWithAgent[] = [];
  let hasNext = false;
  let error: string | null = null;
  // The catalog names and draws the channel a task came from. Fetched here so
  // the listing never has to know which channels exist; an empty one only
  // costs the chip its artwork.
  let catalog: TriggerCatalogEntry[] = [];

  try {
    const [{ data: tasksData, error: tasksError }, catalogResponse] =
      await Promise.all([
        getAllTasks({
          ...pageWindow(page, TASKS_PAGE_SIZE),
          status: statuses.length > 0 ? statuses : undefined,
          search: searchQuery.trim() || undefined,
          created_by: creator.trim() || undefined,
        }),
        listTriggerCatalog(),
      ]);
    if (tasksError) {
      error = t("error.loadFailedDescription");
    } else {
      ({ rows: tasks, hasNext } = takePage(tasksData || [], TASKS_PAGE_SIZE));
    }
    catalog = (catalogResponse.data ?? []) as TriggerCatalogEntry[];
  } catch {
    error = t("error.loadFailedDescription");
  }

  // Checked before the empty branches: a failed load also leaves `tasks`
  // empty, and reporting that as "no tasks yet" hid every backend failure
  // behind a new-workspace message.
  if (error) {
    return (
      <RetryEmptyState
        title={t("error.loadFailed")}
        description={error}
        iconsType="tasks"
      />
    );
  }

  const filtered = Boolean(
    searchQuery.trim() || creator.trim() || statuses.length > 0
  );

  if (tasks.length === 0 && page > 1) {
    return (
      <EmptyState
        title={t("noMatchingTasks")}
        description={t("noTasksOnPageDescription")}
        iconsType="tasks"
        action={{
          label: t("firstPage"),
          href: pageHref("/tasks", searchParams, 1),
        }}
      />
    );
  }

  if (tasks.length === 0 && !filtered) {
    return (
      <EmptyState
        title={t("noTasks")}
        description={t("noTasksDescription")}
        hints={[
          { text: t("noTasksHintStart"), href: "/agents" },
          { text: t("noTasksHintTrigger"), href: "/triggers" },
          { text: t("noTasksHintElsewhere") },
        ]}
        iconsType="tasks"
        // Tasks are started from an agent, so the way out of an empty list is
        // the agent picker -- which carries its own "create an agent" empty
        // state when the workspace has none.
        action={{ label: t("startTaskAction"), href: "/agents" }}
      />
    );
  }

  if (tasks.length === 0) {
    // Filtering by creator without a search term would otherwise render
    // `No tasks match your search ""` -- a quoted empty string.
    const description = searchQuery.trim()
      ? t("noMatchingTasksDescription", { query: searchQuery })
      : t("noTasksByCreatorDescription");
    return (
      <EmptyState
        title={t("noMatchingTasks")}
        description={description}
        iconsType="tasks"
        action={{ label: tCommon("clearSearch"), href: "/tasks" }}
      />
    );
  }

  // Joined here rather than served alongside each task: only the rows actually
  // being rendered need a name, and distinct principals are usually a handful
  // even on a full page. An id the backend cannot resolve is absent from the
  // map, and the cell renders it as unknown.
  //
  // Both kinds of principal a row can mention go in one batch: the task's own
  // creator, and whatever its source points at — for a delegated task, the
  // agent that delegated it.
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
    <>
      <TasksList
        principalNames={principalNames}
        initialTasks={tasks}
        viewMode={viewMode}
        catalog={catalog}
      />
      <TasksPagination
        page={page}
        hasNext={hasNext}
        searchParams={searchParams}
      />
    </>
  );
}
