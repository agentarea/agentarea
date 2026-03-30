import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { getAllTasks, type TaskWithAgent } from "@/lib/api";
import TasksList from "./TasksList";

interface TasksDataProps {
  searchQuery?: string;
  viewMode?: string;
}

export async function TasksData({
  searchQuery = "",
  viewMode = "grid",
}: TasksDataProps) {
  const t = await getTranslations("TasksPage");

  let allTasks: TaskWithAgent[] = [];
  let error: string | null = null;

  try {
    const { data: tasksData, error: tasksError } = await getAllTasks();
    if (tasksError) {
      error = t("error.loadFailed");
    } else {
      allTasks = tasksData || [];
    }
  } catch {
    error = t("error.loadFailed");
  }

  let filteredTasks = allTasks;
  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredTasks = allTasks.filter(
      (task) =>
        task.description?.toLowerCase().includes(query) ||
        task.agent_name?.toLowerCase().includes(query) ||
        task.status?.toLowerCase().includes(query)
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
      />
    );
  }

  if (hasNoResults) {
    return (
      <EmptyState
        title={t("noMatchingTasks")}
        description={t("noMatchingTasksDescription", { query: searchQuery })}
        iconsType="tasks"
      />
    );
  }

  if (error) {
    return <div className="py-6 text-center text-red-500">{error}</div>;
  }

  return <TasksList initialTasks={filteredTasks} viewMode={viewMode} />;
}
