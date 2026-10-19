import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { listStreamSourceTypes } from "@/lib/api";
import { fetchTasksPage, type TasksQuery } from "../actions";
import TasksInfiniteList from "./TasksInfiniteList";

interface TasksDataProps {
  query: TasksQuery;
  viewMode?: string;
}

export async function TasksData({
  query,
  viewMode = "table",
}: TasksDataProps) {
  const t = await getTranslations("TasksPage");
  const tCommon = await getTranslations("Common");

  // The source-types catalog names and draws the provider a task's event came
  // from. Fetched here so the listing never has to know which providers exist;
  // a failed load only costs the chip its name and artwork.
  const [firstPage, typesResponse] = await Promise.all([
    fetchTasksPage(query, 1),
    listStreamSourceTypes(),
  ]);
  if (typesResponse.error) {
    console.error("Failed to load source types:", typesResponse.error);
  }
  const sourceTypes = typesResponse.data ?? [];

  // Checked before the empty branches: reporting a failed load as "no tasks
  // yet" hid every backend failure behind a new-workspace message.
  if (!firstPage) {
    return (
      <RetryEmptyState
        title={t("error.loadFailed")}
        description={t("error.loadFailedDescription")}
        iconsType="tasks"
      />
    );
  }

  const searchQuery = query.search.trim();
  const filtered = Boolean(
    searchQuery || query.creator.trim() || query.statuses.length > 0
  );

  if (firstPage.tasks.length === 0 && !filtered) {
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

  if (firstPage.tasks.length === 0) {
    // Filtering by creator without a search term would otherwise render
    // `No tasks match your search ""` -- a quoted empty string.
    const description = searchQuery
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

  return (
    <TasksInfiniteList
      firstPage={firstPage}
      query={query}
      viewMode={viewMode}
      sourceTypes={sourceTypes}
    />
  );
}
