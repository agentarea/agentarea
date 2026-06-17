"use client";

import { Calendar, Clock, GitFork } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { Badge } from "@/components/ui/badge";

export interface TaskItemData {
  id: string;
  description: string;
  status: string;
  created_at: string;
  agent_name?: string;
  agent_id?: string;
  parameters?: Record<string, unknown>;
}

interface TaskItemProps {
  task: TaskItemData;
  /** Показывать имя агента (по умолчанию true для общего списка задач) */
  showAgentName?: boolean;
}

const statusConfig = {
  running: {
    color: "text-amber-600 border-amber-300",
    label: "Running",
  },
  completed: {
    color: "text-green-600 border-green-300",
    label: "Completed",
  },
  success: {
    color: "text-green-600 border-green-300",
    label: "Success",
  },
  failed: {
    color: "text-red-600 border-red-300",
    label: "Failed",
  },
  blocked: {
    color: "text-gray-500 border-gray-300",
    label: "Blocked",
  },
  error: {
    color: "text-red-600 border-red-300",
    label: "Error",
  },
  paused: {
    color: "text-gray-500 border-gray-300",
    label: "Paused",
  },
  pending: {
    color: "text-gray-500 border-gray-300",
    label: "Pending",
  },
};

export default function TaskItem({
  task,
  showAgentName = true,
}: TaskItemProps) {
  const status =
    statusConfig[task.status as keyof typeof statusConfig] ||
    statusConfig.pending;
  const isDelegation = task.parameters?.source === "agent_delegation";

  return (
    <LinkedCard
      href={`/tasks/${task.id}`}
      title={task.description}
      type="view"
      topRight={
        <Badge
          size="sm"
          variant="outline"
          className={`whitespace-nowrap h-5 px-1.5 font-normal ${status.color}`}
        >
          {status.label}
        </Badge>
      }
    >
      <div className="flex flex-col gap-2 text-xs text-muted-foreground">
        {isDelegation && (
          <div className="flex items-center gap-1.5 text-primary">
            <GitFork className="h-3 w-3" />
            <span>Delegated subtask</span>
          </div>
        )}
        {showAgentName && (
          <div className="flex items-center gap-1.5">
            <AgentAvatar
              agent={{
                id: task.agent_id || task.agent_name || "agent",
                name: task.agent_name,
              }}
              size="xs"
            />
            <span className="truncate">
              {task.agent_name || "Unknown Agent"}
            </span>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex items-center gap-1.5">
            <Calendar className="h-3 w-3" />
            <span>
              {new Date(task.created_at).toLocaleDateString("en", {
                day: "numeric",
                month: "short",
                year: "numeric",
              })}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <Clock className="h-3 w-3" />
            <span>
              {new Date(task.created_at).toLocaleTimeString("en", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
        </div>
      </div>
    </LinkedCard>
  );
}
