"use client";

import { FileText } from "lucide-react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { useTaskContext } from "../TaskContext";

export default function TaskLogsPage() {
  const { task, taskStatus, loading, error } = useTaskContext();

  const getLogLevelColor = (level: string) => {
    if (level === "success") return "text-green-600";
    if (level === "error") return "text-red-600";
    if (level === "warning") return "text-yellow-600";
    return "text-blue-600";
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (error || !task) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        <FileText className="mx-auto mb-4 h-16 w-16 opacity-50" />
        <p>{error || "Task not found"}</p>
      </div>
    );
  }

  const isActive = ["running", "paused"].includes(task.status);
  const currentStatus = task.status;

  return (
    <div className="main-content">
      <h3 className="text-lg font-semibold">Execution Logs</h3>
      <p className="note">Detailed logs of the task execution</p>
        <div className="h-[500px] overflow-y-auto rounded-lg bg-muted p-4 font-mono text-sm">
          {task.created_at && (
            <div className="mb-2">
              <span className="text-muted-foreground">
                [{new Date(task.created_at).toLocaleString()}]
              </span>{" "}
              <span className="text-blue-600">INFO:</span> Task created:{" "}
              {task.description || "No description"}
            </div>
          )}
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

