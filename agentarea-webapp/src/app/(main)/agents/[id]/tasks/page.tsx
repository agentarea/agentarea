import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { getAgent, getAgentTaskStatus, listAgentTasks } from "@/lib/api";
import AgentTasksList from "./components/AgentTasksList";
import { TaskStatus, TaskWithStatus } from "./types";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const agent = await getAgent(id);
  const t = await getTranslations("Metadata");
  return {
    title: agent.data?.name
      ? t("agentTasks", { agentName: agent.data.name })
      : t("agentTasks", { agentName: "Agent" }),
  };
}

export default async function AgentTasksPage({ params }: Props) {
  const { id } = await params;

  // Загружаем начальные данные на сервере
  let initialTasks: TaskWithStatus[] = [];
  try {
    const { data: tasksData, error } = await listAgentTasks(id);
    if (!error && tasksData) {
      // Загружаем статусы для каждой задачи
      const tasksWithStatuses = await Promise.all(
        tasksData.map(async (task) => {
          try {
            const { data: statusData, error: statusError } =
              await getAgentTaskStatus(id, task.id);
            return {
              ...task,
              taskStatus: statusError ? undefined : (statusData as TaskStatus),
            };
          } catch (error) {
            console.error(`Failed to load status for task ${task.id}:`, error);
            return { ...task, taskStatus: undefined };
          }
        })
      );
      initialTasks = tasksWithStatuses;
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
