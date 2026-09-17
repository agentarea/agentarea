import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import {
  getAllTasks,
  listTriggerCatalog,
  resolvePrincipals,
  type TaskWithAgent,
} from "@/lib/api";
import type { TriggerCatalogEntry } from "@/app/(main)/triggers/components/triggerDisplay";
import { getTaskSource } from "@/lib/taskSource";
import TasksList from "./TasksList";

interface TasksDataProps {
  searchQuery?: string;
  /** tasks.created_by to narrow the list to, from the "Started by" cell's link. */
  creator?: string;
  viewMode?: string;
}

export async function TasksData({
  searchQuery = "",
  creator = "",
  viewMode = "table",
}: TasksDataProps) {
  const t = await getTranslations("TasksPage");
  const tCommon = await getTranslations("Common");

  let allTasks: TaskWithAgent[] = [];
  let error: string | null = null;
  // The catalog names and draws the channel a task came from. Fetched here so
  // the listing never has to know which channels exist; an empty one only
  // costs the chip its artwork.
  let catalog: TriggerCatalogEntry[] = [];

  try {
    const [{ data: tasksData, error: tasksError }, catalogResponse] =
      await Promise.all([getAllTasks(), listTriggerCatalog()]);
    if (tasksError) {
      error = t("error.loadFailedDescription");
    } else {
      allTasks = tasksData || [];
    }
    catalog = (catalogResponse.data ?? []) as TriggerCatalogEntry[];
  } catch {
    error = t("error.loadFailedDescription");
  }

  let filteredTasks = allTasks;
  if (creator.trim()) {
    filteredTasks = filteredTasks.filter((task) => task.created_by === creator);
  }
  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredTasks = filteredTasks.filter(
      (task) =>
        task.description?.toLowerCase().includes(query) ||
        task.agent_name?.toLowerCase().includes(query) ||
        task.status?.toLowerCase().includes(query)
    );
  }

  // Checked before the empty branches: a failed load also leaves `allTasks`
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

  const hasNoTasks = allTasks.length === 0;
  const hasNoResults = filteredTasks.length === 0 && !hasNoTasks;

  if (hasNoTasks) {
    return (
      <EmptyState
        title={t("noTasks")}
        description={t("noTasksDescription")}
        iconsType="tasks"
        // Tasks are started from an agent, so the way out of an empty list is
        // the agent picker -- which carries its own "create an agent" empty
        // state when the workspace has none.
        action={{ label: t("startTaskAction"), href: "/agents" }}
      />
    );
  }

  if (hasNoResults) {
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
      filteredTasks
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
      principalNames={principalNames}
      initialTasks={filteredTasks}
      viewMode={viewMode}
      catalog={catalog}
    />
  );
}
