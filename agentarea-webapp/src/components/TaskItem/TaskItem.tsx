"use client";

import { Calendar, CalendarClock, Clock, GitFork } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { TaskStatus } from "@/components/TaskStatus";

export interface TaskItemData {
  id: string;
  description: string;
  status: string;
  created_at: string;
  agent_name?: string | null;
  agent_id?: string;
  parameters?: Record<string, unknown>;
  scheduled_at?: string | null;
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
  const isDelegation = task.parameters?.source === "agent_delegation";

  return (
    <LinkedCard
      href={`/tasks/${task.id}`}
      title={task.description}
      type="view"
      topRight={
        <TaskStatus status={task.status} className="whitespace-nowrap" />
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
        {task.scheduled_at && (
          <div className="flex items-center gap-1.5 text-primary">
            <CalendarClock className="h-3 w-3" />
            <span>
              Runs{" "}
              {new Date(task.scheduled_at).toLocaleString("en", {
                day: "numeric",
                month: "short",
                hour: "2-digit",
                minute: "2-digit",
              })}
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
