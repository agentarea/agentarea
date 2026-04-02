"use client";

import {
  Bot,
  Calendar,
  Clock,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { cn } from "@/lib/utils";
import { TaskStatusIcon } from "@/components/TaskStatusIcon";
import { TaskWithAgent } from "@/lib/api";

export interface TaskItemData {
  id: string;
  description: string;
  status: string;
  created_at: string;
  agent_name?: string;
  agent_id?: string;
}

interface TaskItemProps {
  task: TaskItemData;
  /** Показывать имя агента (по умолчанию true для общего списка задач) */
  showAgentName?: boolean;
}

const statusConfig = {
  running: {
    badgeVariant: "default" as const,
    label: "Running",
  },
  completed: {
    badgeVariant: "success" as const,
    label: "Completed",
  },
  success: {
    badgeVariant: "success" as const,
    label: "Success",
  },
  failed: {
    badgeVariant: "destructive" as const,
    label: "Failed",
  },
  blocked: {
    badgeVariant: "secondary" as const,
    label: "Blocked",
  },
  error: {
    badgeVariant: "destructive" as const,
    label: "Error",
  },
  paused: {
    badgeVariant: "secondary" as const,
    label: "Paused",
  },
  pending: {
    badgeVariant: "secondary" as const,
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

  return (
    <LinkedCard
      href={`/tasks/${task.id}`}
      title={task.description}
      type="view"
      topRight={
        <Badge 
          variant={status.badgeVariant} 
          className="whitespace-nowrap h-5 px-1.5 text-[10px] gap-1 bg-opacity-30 dark:bg-opacity-20 uppercase"
        >
          <TaskStatusIcon 
            status={task.status as TaskWithAgent['status']} 
            className="h-3 w-3" 
          />
          {status.label}
        </Badge>
      }
    >
      <div className="flex flex-col gap-2 text-xs text-muted-foreground">
        {showAgentName && (
          <div className="flex items-center gap-1.5">
            <Bot className="h-3 w-3" />
            <span className="truncate">{task.agent_name || "Unknown Agent"}</span>
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
