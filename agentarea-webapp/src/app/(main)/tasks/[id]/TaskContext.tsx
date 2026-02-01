"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { getAllTasks, getAgentTaskStatus } from "@/lib/browser-api";
import type { TaskWithAgent } from "@/lib/browser-api";

interface TaskData {
  id: string;
  agent_id: string;
  description?: string;
  status: string;
  created_at?: string;
  execution_id?: string;
  agent_name?: string;
  agent_description?: string;
  result?: Record<string, unknown>;
}

interface TaskStatus {
  task_id?: string;
  agent_id?: string;
  execution_id?: string;
  status?: string;
  start_time?: string;
  end_time?: string;
  execution_time?: string;
  message?: string;
  error?: string;
  artifacts?: unknown[];
  usage_metadata?: Record<string, unknown>;
  result?: Record<string, unknown>;
  session_id?: string;
}

interface TaskContextType {
  task: TaskData | null;
  taskStatus: TaskStatus | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const TaskContext = createContext<TaskContextType | undefined>(undefined);

interface TaskProviderProps {
  taskId: string;
  children: React.ReactNode;
}

export function TaskProvider({ taskId, children }: TaskProviderProps) {
  const [task, setTask] = useState<TaskData | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadTask = useCallback(async () => {
    if (!taskId) {
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      // Find task from all tasks
      const { data: allTasks, error: tasksError } = await getAllTasks();
      if (tasksError || !allTasks?.length) {
        throw new Error(
          tasksError instanceof Error
            ? tasksError.message
            : "No tasks found"
        );
      }

      const foundTask = allTasks.find(
        (t: TaskWithAgent) => t.id?.toString() === taskId
      ) as TaskWithAgent | undefined;

      if (!foundTask) {
        throw new Error("Task not found");
      }

      const agentId = foundTask.agent_id.toString();
      const taskIdStr = foundTask.id.toString();

      // Load task and status in parallel
      const [statusResponse] = await Promise.all([
        getAgentTaskStatus(agentId, taskIdStr),
      ]);

      // Set task data
      setTask({
        id: taskIdStr,
        agent_id: agentId,
        description: foundTask.description,
        status: foundTask.status,
        created_at: foundTask.created_at,
        execution_id: foundTask.execution_id || undefined,
        agent_name: foundTask.agent_name,
        agent_description: foundTask.agent_description || undefined,
        result: foundTask.result || undefined,
      });

      // Set status if available
      setTaskStatus(
        statusResponse.error ? null : (statusResponse.data as TaskStatus)
      );
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to load task";
      setError(errorMessage);
      setTask(null);
      setTaskStatus(null);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    loadTask();
  }, [loadTask]);

  return (
    <TaskContext.Provider
      value={{ task, taskStatus, loading, error, refresh: loadTask }}
    >
      {children}
    </TaskContext.Provider>
  );
}

export function useTaskContext() {
  const context = useContext(TaskContext);
  if (!context) {
    throw new Error("useTaskContext must be used within a TaskProvider");
  }
  return context;
}

