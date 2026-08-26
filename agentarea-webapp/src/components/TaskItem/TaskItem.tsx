"use client";

import { useTranslations } from "next-intl";
import { Calendar, Clock, GitFork } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getTaskStatusPresentation } from "@/lib/status";

export interface TaskItemData {
  id: string;
  description: string;
  status: string;
  created_at: string;
  agent_name?: string | null;
  agent_id?: string;
  parameters?: Record<string, unknown>;
}

interface TaskItemProps {
  task: TaskItemData;
  /** Показывать имя агента (по умолчанию true для общего списка задач) */
  showAgentName?: boolean;
}

export default function TaskItem({
  task,
  showAgentName = true,
}: TaskItemProps) {
  const tStatus = useTranslations("TasksPage.status");
  const status = getTaskStatusPresentation(task.status);
  const statusLabel = status.labelKey ? tStatus(status.labelKey) : status.label;
  const isDelegation = task.parameters?.source === "agent_delegation";

  return (
    <LinkedCard
      href={`/tasks/${task.id}`}
      title={task.description}
      type="view"
      topRight={
        <StatusIndicator
          size="sm"
          tone={status.tone}
          pulse={status.pulse}
          className="whitespace-nowrap"
        >
          {statusLabel}
        </StatusIndicator>
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
