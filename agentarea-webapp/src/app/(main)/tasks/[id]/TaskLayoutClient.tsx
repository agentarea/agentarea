"use client";

import { TaskProvider, useTaskContext } from "./TaskContext";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import TaskSubheader from "./components/TaskSubheader";

interface TaskLayoutClientProps {
  taskId: string;
  tasksTitle: string;
  children: React.ReactNode;
}

function TaskLayoutContent({
  taskId,
  tasksTitle,
  children,
}: {
  taskId: string;
  tasksTitle: string;
  children: React.ReactNode;
}) {
  const { task } = useTaskContext();

  // Create breadcrumbs dynamically
  const breadcrumb: { label: string; href?: string }[] = [
    { label: tasksTitle, href: "/tasks" },
  ];

  // Only add agent name and task description if they are available
  if (task?.agent_name) {
    breadcrumb.push({
      label: task.agent_name,
      href: `/agents/${task.agent_id}`,
    });
  }

  if (task?.description) {
    breadcrumb.push({
      label: task.description,
    });
  }

  return (
    <ContentBlock
      header={{
        breadcrumb,
      }}
      subheader={<TaskSubheader taskId={taskId} />}
      className="p-0"
    >
      <div className="h-full">{children}</div>
    </ContentBlock>
  );
}

export default function TaskLayoutClient({
  taskId,
  tasksTitle,
  children,
}: TaskLayoutClientProps) {
  return (
    <TaskProvider taskId={taskId}>
      <TaskLayoutContent taskId={taskId} tasksTitle={tasksTitle}>
        {children}
      </TaskLayoutContent>
    </TaskProvider>
  );
}

