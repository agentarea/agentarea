import { getTranslations } from "next-intl/server";
import { getTask } from "@/lib/api";
import TaskLayoutClient from "./TaskLayoutClient";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function TaskLayout({ params, children }: Props) {
  const { id } = await params;
  const t = await getTranslations("TasksPage");

  // Fetch task server-side — no client loading spinner needed
  const { data: task, error } = await getTask(id);

  return (
    <TaskLayoutClient
      taskId={id}
      tasksTitle={t("title")}
      initialTask={task ?? null}
      initialError={error ? String(error) : null}
    >
      {children}
    </TaskLayoutClient>
  );
}
