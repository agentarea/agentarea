"use client";

import {
  AlertCircle,
  Bot,
  Calendar,
  CheckCircle2,
  Clock,
  Loader2,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { cn } from "@/lib/utils";

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
    icon: Loader2,
    badgeVariant: "default" as const,
    label: "Running",
  },
  completed: {
    icon: CheckCircle2,
    badgeVariant: "success" as const,
    label: "Completed",
  },
  success: {
    icon: CheckCircle2,
    badgeVariant: "success" as const,
    label: "Success",
  },
  failed: {
    icon: XCircle,
    badgeVariant: "destructive" as const,
    label: "Failed",
  },
  error: {
    icon: XCircle,
    badgeVariant: "destructive" as const,
    label: "Error",
  },
  paused: {
    icon: AlertCircle,
    badgeVariant: "secondary" as const,
    label: "Paused",
  },
  pending: {
    icon: Clock,
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
  const StatusIcon = status.icon;

  return (
    <LinkedCard
      href={`/tasks/${task.id}`}
      title={task.description}
      type="view"
      topRight={
        <Badge variant={status.badgeVariant} className="whitespace-nowrap">
          <StatusIcon
            className={cn("h-3 w-3", task.status === "running" && "animate-spin")}
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
