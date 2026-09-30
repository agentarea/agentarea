"use client";

import { FileText } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useTaskContext } from "../TaskContext";

export default function TaskLogsPage() {
  const { task, taskStatus, loading, error } = useTaskContext();


  if (loading) {
    return (
      <div className="space-y-1.5 p-4" aria-hidden="true">
        {Array.from({ length: 12 }).map((_, i) => (
          <Skeleton
            key={i}
            className="h-3"
            style={{ width: `${60 + ((i * 7) % 35)}%` }}
          />
        ))}
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
              <StatusIndicator kind="active" size="sm">
                INFO:
              </StatusIndicator>{" "}
              {task.description || "No description"}
            </div>
          )}
          {taskStatus?.start_time && (
            <div className="mb-2">
              <span className="text-muted-foreground">
                [{new Date(taskStatus.start_time).toLocaleString()}]
              </span>{" "}
              <StatusIndicator kind="active" size="sm">
                INFO:
              </StatusIndicator>{" "}
              started
            </div>
          )}
          {taskStatus?.message && (
            <div className="mb-2">
              <span className="text-muted-foreground">
                [{new Date().toLocaleString()}]
              </span>{" "}
              <StatusIndicator kind="active" size="sm">
                INFO:
              </StatusIndicator>{" "}
              {taskStatus.message}
            </div>
          )}
          {taskStatus?.error && (
            <div className="mb-2">
              <span className="text-muted-foreground">
                [{new Date().toLocaleString()}]
              </span>{" "}
              <StatusIndicator kind="failed" size="sm">
                ERROR:
              </StatusIndicator>{" "}
              {taskStatus.error}
            </div>
          )}
          {taskStatus?.end_time && (
            <div className="mb-2">
              <span className="text-muted-foreground">
                [{new Date(taskStatus.end_time).toLocaleString()}]
              </span>{" "}
              <StatusIndicator
                kind={currentStatus === "completed" ? "done" : "failed"}
                size="sm"
              >
                {currentStatus === "completed" ? "SUCCESS:" : "ERROR:"}
              </StatusIndicator>{" "}
              Task{" "}
              {currentStatus === "completed"
                ? "completed successfully"
                : "execution ended"}
            </div>
          )}
          {isActive && currentStatus === "running" && (
            <div>
              <span className="text-muted-foreground">
                [{new Date().toLocaleString()}]
              </span>{" "}
              <StatusIndicator kind="running" size="sm">
                INFO: Task is currently running...
              </StatusIndicator>
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

