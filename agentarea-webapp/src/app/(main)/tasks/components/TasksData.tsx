import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { getAllTasks, type TaskWithAgent } from "@/lib/api";
import TasksView, { type TasksInitialState } from "./TasksView";

interface TasksDataProps {
  initial: TasksInitialState;
}

export async function TasksData({ initial }: TasksDataProps) {
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

  if (error) {
    return <div className="py-6 text-center text-red-500">{error}</div>;
  }

  if (allTasks.length === 0) {
    return (
      <EmptyState
        title={t("noTasks")}
        description={t("noTasksDescription")}
        iconsType="tasks"
      />
    );
  }

  return <TasksView tasks={allTasks} initial={initial} />;
}
