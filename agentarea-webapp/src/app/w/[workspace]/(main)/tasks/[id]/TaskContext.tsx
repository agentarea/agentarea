"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useTranslations } from "next-intl";
import type { TaskProvenance, TaskSummary } from "@/api/client/types.gen";
import type { TaskRequester } from "@/components/TaskInfoPanel/types";
import {
  apiErrorMessage,
  formatApiError,
  isApiNotFound,
} from "@/lib/api-errors";
import {
  getAgentTaskStatusAction as getAgentTaskStatus,
  getTaskAction as getTask,
} from "@/lib/server-actions";
import type {
  EffectivePolicy,
  EffectivePolicyResponse,
} from "@/types/policies";
import {
  getTaskPolicySnapshotAction as getTaskPolicySnapshot,
  getTaskSummaryAction as getTaskSummary,
} from "./actions";

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
  parameters?: Record<string, unknown>;
  provenance?: TaskProvenance | null;
}

interface TaskStatus {
  task_id?: string;
  agent_id?: string;
  execution_id?: string;
  status?: string;
  execution_status?: string;
  /** The workflow holds a signal-based pause; status stays "running" meanwhile. */
  paused?: boolean;
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
  /** The person who started the task, resolved on the server. */
  requester: TaskRequester | null;
  taskStatus: TaskStatus | null;
  taskSummary: TaskSummary | null;
  policy: EffectivePolicy | null;
  policyError: string | null;
  statusError: string | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  /**
   * The status the open conversation's event stream reports, published by the
   * overview page; null on tabs without a live stream.
   */
  liveStatus: string | null;
  setLiveStatus: (status: string | null) => void;
}

const TaskContext = createContext<TaskContextType | undefined>(undefined);

function parseTaskData(raw: unknown): TaskData | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  return {
    id: String(r.id),
    agent_id: String(r.agent_id),
    description: r.description as string | undefined,
    status: r.status as string,
    created_at: r.created_at as string | undefined,
    execution_id: r.execution_id ? String(r.execution_id) : undefined,
    agent_name: r.agent_name as string | undefined,
    agent_description: r.agent_description
      ? String(r.agent_description)
      : undefined,
    result:
      typeof r.result === "object" && r.result !== null
        ? (r.result as Record<string, unknown>)
        : undefined,
    parameters:
      typeof r.parameters === "object" && r.parameters !== null
        ? (r.parameters as Record<string, unknown>)
        : undefined,
    provenance:
      typeof r.provenance === "object" && r.provenance !== null
        ? (r.provenance as TaskProvenance)
        : undefined,
  };
}

interface TaskProviderProps {
  taskId: string;
  initialTask?: unknown;
  initialError?: string | null;
  requester?: TaskRequester | null;
  children: React.ReactNode;
}

export function TaskProvider({
  taskId,
  initialTask,
  initialError,
  requester = null,
  children,
}: TaskProviderProps) {
  const [task, setTask] = useState<TaskData | null>(() =>
    parseTaskData(initialTask)
  );
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [taskSummary, setTaskSummary] = useState<TaskSummary | null>(null);
  const t = useTranslations("TaskInfoPanel");
  const [statusError, setStatusError] = useState<string | null>(null);
  const [policy, setPolicy] = useState<EffectivePolicy | null>(null);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!initialTask && !initialError);
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);

  const loadTask = useCallback(async () => {
    if (!taskId) {
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const result = await getTask(taskId);
      if (result.error || !result.data) {
        setError(
          isApiNotFound(result)
            ? null
            : apiErrorMessage(result, t("taskLoadFailed"))
        );
        setTask(null);
        setTaskStatus(null);
        return;
      }

      setTask(parseTaskData(result.data));
    } catch (err) {
      console.error("Failed to load task", err);
      setError(`${t("taskLoadFailed")}: ${formatApiError(err)}`);
      setTask(null);
      setTaskStatus(null);
    } finally {
      setLoading(false);
    }
  }, [taskId, t]);

  const statusTaskId = task?.id;
  const statusAgentId = task?.agent_id;

  // Load status in background (non-blocking, uses Temporal)
  useEffect(() => {
    if (!statusTaskId || !statusAgentId) return;
    const loadStatus = async () => {
      setStatusError(null);
      try {
        const res = await getAgentTaskStatus(statusAgentId, statusTaskId);
        if (res.error) {
          setStatusError(apiErrorMessage(res, t("statusLoadFailed")));
          return;
        }
        setTaskStatus(res.data as TaskStatus);
      } catch (err) {
        console.error("Failed to load task status", err);
        setStatusError(`${t("statusLoadFailed")}: ${formatApiError(err)}`);
      }
    };
    loadStatus();
  }, [statusAgentId, statusTaskId, t]);

  useEffect(() => {
    setTaskSummary(null);
    if (!statusTaskId || !statusAgentId) return;

    let cancelled = false;
    const loadSummary = async () => {
      try {
        const res = await getTaskSummary(statusAgentId, statusTaskId);
        if (!cancelled && !res.error) {
          setTaskSummary(res.data ?? null);
        }
      } catch (err) {
        if (!cancelled) {
          console.error("Failed to load task summary", err);
        }
      }
    };
    void loadSummary();
    return () => {
      cancelled = true;
    };
  }, [statusAgentId, statusTaskId]);

  const policyTaskId = task?.id;

  // Tasks without a snapshot return 404, which means "no policy".
  useEffect(() => {
    if (!policyTaskId) return;
    const loadPolicy = async () => {
      setPolicyError(null);
      try {
        const res = await getTaskPolicySnapshot(policyTaskId);
        if (res.error) {
          setPolicy(null);
          if (!isApiNotFound(res)) {
            setPolicyError(apiErrorMessage(res, t("policyLoadFailed")));
          }
          return;
        }
        setPolicy(
          (res.data as EffectivePolicyResponse | undefined)?.effective_policy ??
            null
        );
      } catch (err) {
        console.error("Failed to load task policy", err);
        setPolicyError(`${t("policyLoadFailed")}: ${formatApiError(err)}`);
      }
    };
    loadPolicy();
  }, [policyTaskId, t]);

  // Only fetch client-side if no server data was provided
  useEffect(() => {
    if (!initialTask && !initialError) {
      loadTask();
    }
  }, [initialError, initialTask, loadTask]);

  return (
    <TaskContext.Provider
      value={{
        task,
        requester,
        taskStatus,
        taskSummary,
        policy,
        policyError,
        statusError,
        loading,
        error,
        refresh: loadTask,
        liveStatus,
        setLiveStatus,
      }}
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
