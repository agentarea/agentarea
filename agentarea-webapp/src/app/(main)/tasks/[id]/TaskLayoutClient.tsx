"use client";

import { TaskProvider, useTaskContext } from "./TaskContext";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import TaskSubheader from "./components/TaskSubheader";

interface TaskLayoutClientProps {
  taskId: string;
  tasksTitle: string;
  initialTask?: any;
  initialError?: string | null;
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

  // Use fallback values during loading
  const agentName = task?.agent_name || `Agent ${task?.agent_id || "..."}`;
  const taskLabel = task?.description || `Task ${taskId.slice(0, 8)}...`;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: tasksTitle, href: "/tasks" },
          {
            label: agentName,
            href: task?.agent_id ? `/agents/${task.agent_id}` : undefined,
          },
          { label: taskLabel },
        ],
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
  initialTask,
  initialError,
  children,
}: TaskLayoutClientProps) {
  return (
    <TaskProvider taskId={taskId} initialTask={initialTask} initialError={initialError}>
      <TaskLayoutContent taskId={taskId} tasksTitle={tasksTitle}>
        {children}
      </TaskLayoutContent>
    </TaskProvider>
  );
}

