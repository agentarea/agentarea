import { getTranslations } from "next-intl/server";
import TaskLayoutClient from "./TaskLayoutClient";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function TaskLayout({ params, children }: Props) {
  const { id } = await params;
  const t = await getTranslations("TasksPage");

  return (
    <TaskLayoutClient taskId={id} tasksTitle={t("title")}>
      {children}
    </TaskLayoutClient>
  );
}
