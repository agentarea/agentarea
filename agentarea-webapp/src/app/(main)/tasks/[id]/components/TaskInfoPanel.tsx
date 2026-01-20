import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Bot, Clock, Hash } from "lucide-react";

interface Task {
  id: string;
  description?: string;
  agent_id: string;
  agent_name?: string;
  agent_description?: string;
  created_at?: string;
  execution_id?: string | null;
  result?: Record<string, unknown>;
}

interface TaskInfoPanelProps {
  task: Task;
  currentStatus: string;
  isActive: boolean;
  startTime: string;
  endTime?: string;
  executionTime: string;
}

export default function TaskInfoPanel({
  task,
  currentStatus,
  isActive,
  startTime,
  endTime,
  executionTime,
}: TaskInfoPanelProps) {
  return (
    <div className="h-full overflow-auto">
      <div className="space-y-4 py-4">
        {/* Compact Header */}
        <div className="flex flex-row justify-between items-center gap-5">
            <h3 className="truncate font-semibold text-gray-900 dark:text-gray-100">
                {task.description || "No description"}
            </h3>
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
            <div className="text-xs text-gray-600 dark:text-gray-400 flex items-center gap-2">
                <div className="flex items-center gap-1">
                    <Hash className="h-4 w-4 text-primary" /> ID:
                </div>
                <span className="rounded bg-gray-100 px-1 py-0.5 font-mono text-sm dark:bg-gray-800">
                {task.id}
                </span>
            </div>
            <div className="text-xs text-gray-600 flex items-center gap-2 dark:text-gray-400">
                <div className="flex items-center gap-1"><Bot className="h-4 w-4 text-primary" /> Agent:</div>
                <Link 
                    href={`/agents/${task.agent_id}`}
                    className="px-1 py-0.5 text-sm dark:bg-gray-800 hover:text-primary hover:underline transition-colors"
                >
                    {task.agent_name || `Agent ${task.agent_id}`}
                </Link>
            </div>
            <div className="text-xs text-gray-600 flex items-center gap-2 dark:text-gray-400">
                <div className="flex items-center gap-1">
                    <Clock className="h-4 w-4 text-primary" /> 
                    {isActive ? "Started" : endTime ? "Ended" : "Created"}:
                </div>
                <span className="px-1 py-0.5 text-sm dark:bg-gray-800">
                {isActive 
                    ? new Date(startTime).toLocaleDateString() 
                    : endTime 
                        ? `${executionTime}`
                        : task.created_at
                        ? `${new Date(task.created_at).toLocaleDateString()}`
                        : "N/A"
                }
                </span>
            </div>
      </div>
    </div>
  );
}

