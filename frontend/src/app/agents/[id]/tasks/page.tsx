import AgentTasksList from "./components/AgentTasksList";
import { listAgentTasks, getAgentTaskStatus, pauseAgentTask, resumeAgentTask, cancelAgentTask } from "@/lib/api";
import { revalidatePath } from "next/cache";
import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";

interface Props {
  params: Promise<{ id: string }>;
}

interface Task {
  id: string;
  description: string;
  status: string;
  created_at: string;
  agent_id: string;
}

interface TaskStatus {
  task_id: string;
  agent_id: string;
  execution_id: string;
  status: string;
  start_time?: string;
  end_time?: string;
  execution_time?: string;
  error?: string;
  result?: any;
  message?: string;
  artifacts?: any;
  session_id?: string;
  usage_metadata?: any;
}

interface TaskWithStatus extends Task {
  taskStatus?: TaskStatus;
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
            const { data: statusData, error: statusError } = await getAgentTaskStatus(id, task.id);
            return {
              ...task,
              taskStatus: statusError ? undefined : statusData as TaskStatus,
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

  // Создаем серверные action handlers
  const handlePauseTask = async (taskId: string) => {
    "use server";
    const result = await pauseAgentTask(id, taskId);
    if (!result.error) {
      // Обновляем данные после успешного действия
      revalidatePath(`/agents/${id}/tasks`);
    }
    return result;
  };

  const handleResumeTask = async (taskId: string) => {
    "use server";
    const result = await resumeAgentTask(id, taskId);
    if (!result.error) {
      // Обновляем данные после успешного действия
      revalidatePath(`/agents/${id}/tasks`);
    }
    return result;
  };

  const handleCancelTask = async (taskId: string) => {
    "use server";
    const result = await cancelAgentTask(id, taskId);
    if (!result.error) {
      // Обновляем данные после успешного действия
      revalidatePath(`/agents/${id}/tasks`);
    }
    return result;
  };

  return (
    <Suspense
      fallback={(
        <div className="flex items-center justify-center h-32">
          <LoadingSpinner />
        </div>
      )}
    >
      <AgentTasksList 
        agentId={id} 
        initialTasks={initialTasks}
        onPauseTask={handlePauseTask}
        onResumeTask={handleResumeTask}
        onCancelTask={handleCancelTask}
      />
    </Suspense>
  );
}


