import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Bot, Clock, Database, Download, RefreshCw, Share2 } from "lucide-react";
import LiveEventIndicator from "@/components/TaskEvents/LiveEventIndicator";

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
  events: unknown[];
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
  return (
    <div className="rounded-lg border border-gray-200 bg-gradient-to-r from-white to-gray-50 p-4 shadow-sm dark:border-gray-700 dark:from-gray-900 dark:to-gray-800">
      <div className="flex items-start gap-4">
        {/* Smaller Status Indicator */}
        <div className="flex-shrink-0">
          <div
            className={`flex h-10 w-10 items-center justify-center rounded-lg ${
              currentStatus === "running"
                ? "bg-blue-50 dark:bg-blue-900/30"
                : currentStatus === "completed" ||
                    currentStatus === "success"
                  ? "bg-green-50 dark:bg-green-900/30"
                  : currentStatus === "paused"
                    ? "bg-yellow-50 dark:bg-yellow-900/30"
                    : "bg-red-50 dark:bg-red-900/30"
            }`}
          >
            <div
              className={`h-4 w-4 rounded-full ${
                currentStatus === "running"
                  ? "animate-pulse bg-blue-500"
                  : currentStatus === "completed" ||
                      currentStatus === "success"
                    ? "bg-green-500"
                    : currentStatus === "paused"
                      ? "bg-yellow-500"
                      : "bg-red-500"
              }`}
            />
          </div>
        </div>

        {/* Compact Main Content */}
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-2">
            <h1 className="truncate text-xl font-bold text-gray-900 dark:text-gray-100">
              {task.description}
            </h1>
            <Badge
              className={`px-2 py-0.5 text-xs ${
                currentStatus === "running"
                  ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
                  : currentStatus === "completed" ||
                      currentStatus === "success"
                    ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
                    : currentStatus === "paused"
                      ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300"
                      : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
              }`}
            >
              {currentStatus.charAt(0).toUpperCase() +
                currentStatus.slice(1)}
            </Badge>
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
                <Database className="h-3 w-3 text-purple-600" />
                <span className="font-mono font-medium text-gray-900 dark:text-gray-100">
                  {task.execution_id.slice(-8)}
                </span>
              </div>
            )}

            {/* Live Event Indicator */}
            <div className="flex items-center gap-2 text-xs">
              <LiveEventIndicator
                connected={eventsConnected}
                latestEvent={events[events.length - 1]}
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

