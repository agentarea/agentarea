"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { FileText } from "lucide-react";
import { LoadingSpinner } from "@/components/LoadingSpinner";

interface TaskData {
  id: string;
  agent_id: string;
  description: string;
  status: string;
  created_at: string;
}

interface TaskStatus {
  start_time?: string;
  end_time?: string;
  message?: string;
  error?: string;
}

export default function TaskLogsPage() {
  const params = useParams();
  const id = Array.isArray(params.id) ? params.id[0] : (params.id as string);

  const [task, setTask] = useState<TaskData | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const loadTask = useCallback(async () => {
    try {
      setLoading(true);
      const { getAllTasks, getAgentTaskStatus } = await import(
        "@/lib/browser-api"
      );
      const { data: allTasks } = await getAllTasks();
      const foundTask = allTasks?.find((t: any) => t.id?.toString() === id);

      if (foundTask) {
        setTask({
          id: foundTask.id.toString(),
          agent_id: foundTask.agent_id.toString(),
          description: foundTask.description,
          status: foundTask.status,
          created_at: foundTask.created_at,
        });

        const statusResponse = await getAgentTaskStatus(
          foundTask.agent_id.toString(),
          foundTask.id.toString()
        );
        if (!statusResponse.error && statusResponse.data) {
          setTaskStatus(statusResponse.data as TaskStatus);
        }
      }
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadTask();
  }, [loadTask]);

  const getLogLevelColor = (level: string) => {
    if (level === "success") return "text-green-600";
    if (level === "error") return "text-red-600";
    if (level === "warning") return "text-yellow-600";
    return "text-blue-600";
  };

  if (loading) {
    return (
      <div className="p-8">
        <LoadingSpinner />
      </div>
    );
  }

  if (!task) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        <FileText className="mx-auto mb-4 h-16 w-16 opacity-50" />
        <p>Task not found</p>
      </div>
    );
  }

  const isActive = ["running", "paused"].includes(task.status);
  const currentStatus = taskStatus ? task.status : task.status;

  return (
    <div className="main-content">
        <h3>Execution Logs</h3>
        <p className="note">Detailed logs of the task execution</p>
        <div className="h-[500px] overflow-y-auto rounded-lg bg-muted p-4 font-mono text-sm">
          <div className="mb-2">
            <span className="text-muted-foreground">
              [{new Date(task.created_at).toLocaleString()}]
            </span>{" "}
            <span className="text-blue-600">INFO:</span> Task created:{" "}
            {task.description}
          </div>
          {taskStatus?.start_time && (
            <div className="mb-2">
              <span className="text-muted-foreground">
                [{new Date(taskStatus.start_time).toLocaleString()}]
              </span>{" "}
              <span className="text-blue-600">INFO:</span> Task execution
              started
            </div>
          )}
          {taskStatus?.message && (
            <div className="mb-2">
              <span className="text-muted-foreground">
                [{new Date().toLocaleString()}]
              </span>{" "}
              <span className="text-blue-600">INFO:</span> {taskStatus.message}
            </div>
          )}
          {taskStatus?.error && (
            <div className="mb-2">
              <span className="text-muted-foreground">
                [{new Date().toLocaleString()}]
              </span>{" "}
              <span className="text-red-600">ERROR:</span> {taskStatus.error}
            </div>
          )}
          {taskStatus?.end_time && (
            <div className="mb-2">
              <span className="text-muted-foreground">
                [{new Date(taskStatus.end_time).toLocaleString()}]
              </span>{" "}
              <span
                className={getLogLevelColor(
                  currentStatus === "completed" ? "success" : "error"
                )}
              >
                {currentStatus === "completed" ? "SUCCESS" : "ERROR"}:
              </span>{" "}
              Task{" "}
              {currentStatus === "completed"
                ? "completed successfully"
                : "execution ended"}
            </div>
          )}
          {isActive && currentStatus === "running" && (
            <div className="animate-pulse">
              <span className="text-muted-foreground">
                [{new Date().toLocaleString()}]
              </span>{" "}
              <span className="text-blue-600">INFO:</span> Task is currently
              running...
            </div>
          )}
          {!isActive && !taskStatus?.end_time && (
            <div className="py-8 text-center text-muted-foreground">
              <FileText className="mx-auto mb-2 h-8 w-8 opacity-50" />
              <p>No detailed execution logs available</p>
              <p className="mt-1 text-xs">
                Logs will be available in future versions
              </p>
            </div>
          )}
        </div>
    </div>
  );
}

