import { useTranslations } from "next-intl";
import {
  Bot,
  Clock,
  Database,
  Download,
  RefreshCw,
  Share2,
} from "lucide-react";
import LiveEventIndicator from "@/components/TaskEvents/LiveEventIndicator";
import { Button } from "@/components/ui/button";
import { TaskStatusIcon } from "@/components/ui/task-status-icon";
import { TaskWithAgent } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DisplayEvent } from "@/types/events";

interface TaskHeaderProps {
  task: {
    id: string;
    description: string;
    agent_id: string;
    agent_name?: string;
    created_at: string;
    execution_id?: string | null;
  };
  currentStatus: string;
  isActive: boolean;
  startTime: string;
  endTime?: string;
  executionTime: string;
  eventsConnected: boolean;
  events: DisplayEvent[];
  refreshing: boolean;
  onRefresh: () => void;
  controlButtons: React.ReactNode;
}

export default function TaskHeader({
  task,
  currentStatus,
  isActive,
  startTime,
  endTime,
  executionTime,
  eventsConnected,
  events,
  refreshing,
  onRefresh,
  controlButtons,
}: TaskHeaderProps) {
  const tStatus = useTranslations("TasksPage.status");
  const status = currentStatus as TaskWithAgent["status"];

  const label = [
    "running",
    "completed",
    "success",
    "failed",
    "error",
    "paused",
    "pending",
  ].includes(status)
    ? tStatus(status)
    : status.charAt(0).toUpperCase() + status.slice(1);

  const colorClass =
    {
      completed: "text-green-600 dark:text-green-500",
      success: "text-green-600 dark:text-green-500",
      failed: "text-red-600 dark:text-red-500",
      error: "text-red-600 dark:text-red-500",
      running: "text-primary",
      in_progress: "text-primary",
      pending: "text-muted-foreground",
      paused: "text-muted-foreground",
    }[status] || "text-muted-foreground";

  return (
    <div className="rounded-lg border border-gray-200 bg-gradient-to-r from-white to-gray-50 p-4 shadow-sm dark:border-gray-700 dark:from-gray-900 dark:to-gray-800">
      <div className="flex items-start gap-4">
        {/* Smaller Status Indicator */}
        <div className="flex-shrink-0">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800">
            <TaskStatusIcon status={status} className="h-6 w-6" />
          </div>
        </div>

        {/* Compact Main Content */}
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-2">
            <h1 className="truncate text-xl font-bold text-gray-900 dark:text-gray-100">
              {task.description}
            </h1>
            <div className="flex items-center gap-1.5 ml-2">
              <span
                className={cn(
                  "text-[11px] font-normal uppercase tracking-wider",
                  colorClass
                )}
              >
                {label}
              </span>
            </div>
          </div>

          <p className="mb-2 text-sm text-gray-600 dark:text-gray-400">
            ID:{" "}
            <span className="rounded bg-gray-100 px-1 py-0.5 font-mono text-xs dark:bg-gray-800">
              {task.id}
            </span>
          </p>

          {/* Compact Meta Information */}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
              <Bot className="h-3 w-3 text-blue-600" />
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {task.agent_name || `Agent ${task.agent_id}`}
              </span>
            </div>

            <div className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
              <Clock className="h-3 w-3 text-green-600" />
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {isActive
                  ? `Started ${new Date(startTime).toLocaleDateString()}`
                  : endTime
                    ? `${executionTime}`
                    : `${new Date(task.created_at).toLocaleDateString()}`}
              </span>
            </div>

            {task.execution_id && (
              <div className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
                <Database className="h-3 w-3 text-sky-600" />
                <span className="font-mono font-medium text-gray-900 dark:text-gray-100">
                  {task.execution_id.slice(-8)}
                </span>
              </div>
            )}

            {/* Live Event Indicator */}
            <div className="flex items-center gap-2 text-xs">
              <LiveEventIndicator
                connected={eventsConnected}
                latestEvent={
                  events.length > 0 ? events[events.length - 1] : undefined
                }
                eventCount={events.length}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Compact Action Buttons */}
      <div className="mt-4 flex flex-wrap gap-1">
        {/* Task Control Buttons */}
        {controlButtons}

        <Button
          variant="outline"
          size="sm"
          className="gap-1"
          onClick={onRefresh}
          disabled={refreshing}
        >
          <RefreshCw
            className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
        <Button variant="outline" size="sm" className="gap-1">
          <Download className="h-3 w-3" />
          Export
        </Button>
        <Button variant="outline" size="sm" className="gap-1">
          <Share2 className="h-3 w-3" />
          Share
        </Button>
      </div>
    </div>
  );
}
