import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import TaskSubheader from "./components/TaskSubheader";
import { getAllTasks } from "@/lib/api";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function TaskLayout({ params, children }: Props) {
  const { id } = await params;
  const t = await getTranslations("TasksPage");

  // Fetch task data to get agent info for breadcrumb
  const { data: allTasks } = await getAllTasks();
  const task = allTasks?.find((t: any) => t.id?.toString() === id);

  const agentName = task?.agent_name || `Agent ${task?.agent_id || "Unknown"}`;
  const taskLabel = task?.description || `Task ${id.slice(0, 8)}...`;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/tasks" },
          {
            label: agentName,
            href: task?.agent_id ? `/agents/${task.agent_id}` : undefined,
          },
          { label: taskLabel },
        ],
      }}
      subheader={<TaskSubheader taskId={id} />}
      className="p-0"
    >
      <div className="h-full">{children}</div>
    </ContentBlock>
  );
}
