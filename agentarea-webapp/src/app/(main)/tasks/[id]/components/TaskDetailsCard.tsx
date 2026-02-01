import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Bot,
  CheckCircle2,
  Layers,
  Loader2,
  Pause,
  XCircle,
} from "lucide-react";

interface TaskDetailsCardProps {
  task: {
    agent_id: string;
    agent_name?: string;
    agent_description?: string;
    created_at: string;
    execution_id?: string | null;
  };
  currentStatus: string;
  startTime: string;
  endTime?: string;
  executionTime: string;
}

export default function TaskDetailsCard({
  task,
  currentStatus,
  startTime,
  endTime,
  executionTime,
}: TaskDetailsCardProps) {
  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Layers className="h-4 w-4 text-primary" />
          </div>
          <div>
            <CardTitle className="text-base">Task Details</CardTitle>
            <CardDescription className="text-xs">
              Core information
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Compact Status */}
        <div className="flex items-center justify-between rounded-lg border bg-gray-50 p-2 dark:bg-gray-800">
          <div className="flex items-center gap-2">
            <div
              className={`flex h-6 w-6 items-center justify-center rounded ${
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
              {currentStatus === "running" ? (
                <Loader2 className="h-3 w-3 animate-spin text-blue-600" />
              ) : currentStatus === "completed" ||
                currentStatus === "success" ? (
                <CheckCircle2 className="h-3 w-3 text-green-600" />
              ) : currentStatus === "paused" ? (
                <Pause className="h-3 w-3 text-yellow-600" />
              ) : (
                <XCircle className="h-3 w-3 text-red-600" />
              )}
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                Status
              </p>
            </div>
          </div>
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

        {/* Compact Agent Info */}
        <div className="rounded-lg border bg-gray-50 p-2 dark:bg-gray-800">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-blue-50 dark:bg-blue-900/30">
              <Bot className="h-3 w-3 text-blue-600" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                {task.agent_name || `Agent ${task.agent_id}`}
              </p>
              <p className="truncate text-xs text-gray-600 dark:text-gray-400">
                {task.agent_description || "No description available"}
              </p>
            </div>
          </div>
        </div>

        {/* Compact Timing Information */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-600 dark:text-gray-400">
              Created
            </span>
            <span className="font-medium text-gray-900 dark:text-gray-100">
              {new Date(task.created_at).toLocaleDateString()}
            </span>
          </div>
          {startTime && startTime !== task.created_at && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-gray-600 dark:text-gray-400">
                Started
              </span>
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {new Date(startTime).toLocaleDateString()}
              </span>
            </div>
          )}
          {endTime && (
            <>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-600 dark:text-gray-400">
                  Completed
                </span>
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {new Date(endTime).toLocaleDateString()}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-600 dark:text-gray-400">
                  Duration
                </span>
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {executionTime}
                </span>
              </div>
            </>
          )}
        </div>

        {/* Compact Execution ID */}
        {task.execution_id && (
          <div className="rounded bg-gray-50 p-2 dark:bg-gray-700">
            <p className="mb-0.5 text-xs text-gray-600 dark:text-gray-400">
              Execution ID
            </p>
            <code className="break-all font-mono text-xs text-gray-900 dark:text-gray-100">
              {task.execution_id}
            </code>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

