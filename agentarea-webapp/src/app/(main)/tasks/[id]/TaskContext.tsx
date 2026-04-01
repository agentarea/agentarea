"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { getTaskAction as getTask, getAgentTaskStatusAction as getAgentTaskStatus } from "@/lib/server-actions";
import type { TaskWithAgent } from "@/lib/api";

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

function parseTaskData(raw: any): TaskData | null {
  if (!raw) return null;
  return {
    id: String(raw.id),
    agent_id: String(raw.agent_id),
    description: raw.description,
    status: raw.status,
    created_at: raw.created_at,
    execution_id: raw.execution_id || undefined,
    agent_name: raw.agent_name,
    agent_description: raw.agent_description || undefined,
    result: typeof raw.result === "object" && raw.result !== null ? raw.result as Record<string, unknown> : undefined,
  };
}

interface TaskProviderProps {
  taskId: string;
  initialTask?: any;
  initialError?: string | null;
  children: React.ReactNode;
}

export function TaskProvider({ taskId, initialTask, initialError, children }: TaskProviderProps) {
  const [task, setTask] = useState<TaskData | null>(() => parseTaskData(initialTask));
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [loading, setLoading] = useState(!initialTask && !initialError);
  const [error, setError] = useState<string | null>(initialError ?? null);

  const loadTask = useCallback(async () => {
    if (!taskId) {
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const { data: foundTask, error: taskError } = await getTask(taskId);
      if (taskError || !foundTask) {
        throw new Error("Task not found");
      }

      setTask(parseTaskData(foundTask));
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

  // Load status in background (non-blocking, uses Temporal)
  useEffect(() => {
    if (!task) return;
    const loadStatus = async () => {
      try {
        const res = await getAgentTaskStatus(task.agent_id, task.id);
        if (!res.error) setTaskStatus(res.data as TaskStatus);
      } catch {
        // Status is optional — page works without it
      }
    };
    loadStatus();
  }, [task?.id]);

  // Only fetch client-side if no server data was provided
  useEffect(() => {
    if (!initialTask && !initialError) {
      loadTask();
    }
  }, []);

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
