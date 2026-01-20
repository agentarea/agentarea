"use client";

import { BarChart } from "lucide-react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { useTaskContext } from "../TaskContext";

export default function TaskMetricsPage() {
  const { task, taskStatus, loading, error } = useTaskContext();

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
        <BarChart className="mx-auto mb-4 h-16 w-16 opacity-50" />
        <p>{error || "Task not found"}</p>
      </div>
    );
  }

  const currentStatus = task.status;
  const executionTime = taskStatus?.execution_time || "N/A";

  return (
    <div className="main-content">
      <h3 className="text-lg font-semibold">Performance Metrics</h3>
      <p className="note">Key metrics for this task execution</p>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg bg-muted p-4">
            <div className="mb-1 text-sm text-muted-foreground">
              Execution Time
            </div>
            <div className="text-2xl font-bold">{executionTime}</div>
          </div>
          <div className="rounded-lg bg-muted p-4">
            <div className="mb-1 text-sm text-muted-foreground">Status</div>
            <div className="text-2xl font-bold">{currentStatus}</div>
          </div>
          <div className="rounded-lg bg-muted p-4">
            <div className="mb-1 text-sm text-muted-foreground">
              Execution ID
            </div>
            <div className="truncate text-lg font-bold">
              {task?.execution_id || "N/A"}
            </div>
          </div>
          <div className="rounded-lg bg-muted p-4">
            <div className="mb-1 text-sm text-muted-foreground">Usage Data</div>
            <div className="text-2xl font-bold">
              {taskStatus?.usage_metadata ? "Available" : "N/A"}
            </div>
          </div>
        </div>
        {taskStatus?.usage_metadata && (
          <div className="mt-6">
            <h4 className="mb-2 text-sm font-medium">Usage Metadata</h4>
            <div className="max-h-40 overflow-y-auto rounded-lg bg-muted p-3 font-mono text-sm">
              <pre>{JSON.stringify(taskStatus.usage_metadata, null, 2)}</pre>
            </div>
          </div>
        )}
        <div className="mt-8 flex justify-center">
          <div className="text-center text-muted-foreground">
            <BarChart className="mx-auto mb-4 h-32 w-32 opacity-50" />
            <p>
              Detailed performance charts will be available in future versions
            </p>
            <p className="mt-1 text-xs">
              Metrics are collected from Temporal workflow execution
            </p>
          </div>
        </div>
    </div>
  );
}

