import type { Metadata } from "next";
import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { listAgentTasks } from "@/lib/api";
import AgentTasksList from "./components/AgentTasksList";
import { TaskStatus, TaskWithStatus } from "./types";

export const metadata: Metadata = {
  title: "Agent Tasks",
};

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentTasksPage({ params }: Props) {
  const { id } = await params;

  // Загружаем начальные данные на сервере
  let initialTasks: TaskWithStatus[] = [];
  try {
    const { data: tasksData, error } = await listAgentTasks(id);
    if (!error && tasksData) {
      initialTasks = tasksData.map((task) => ({ ...task, taskStatus: undefined }));
    }
  } catch (error) {
    console.error("Failed to load initial tasks:", error);
  }

  return (
    <Suspense
      fallback={
        <div className="flex h-32 items-center justify-center">
          <LoadingSpinner />
        </div>
      }
    >
      <AgentTasksList agentId={id} initialTasks={initialTasks} />
    </Suspense>
  );
}
