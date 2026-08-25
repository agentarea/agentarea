import { getTranslations } from "next-intl/server";
import { getTask } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import TaskLayoutClient from "./TaskLayoutClient";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function TaskLayout({ params, children }: Props) {
  const { id } = await params;
  const t = await getTranslations("TasksPage");

  // Fetch task server-side — no client loading spinner needed
  const result = await getTask(id);

  return (
    <TaskLayoutClient
      taskId={id}
      tasksTitle={t("title")}
      initialTask={result.data ?? null}
      initialError={
        result.error ? apiErrorMessage(result, "Failed to load task") : null
      }
    >
      {children}
    </TaskLayoutClient>
  );
}
