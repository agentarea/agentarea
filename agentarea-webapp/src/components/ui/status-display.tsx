"use client";

import { StatusLabel } from "@/components/ui/status-label";
import { TaskStatusIcon } from "@/components/ui/task-status-icon";
import { TaskWithAgent } from "@/lib/api";
import { cn } from "@/lib/utils";

type Status = TaskWithAgent["status"] | string;

interface StatusDisplayProps {
  status: Status;
  className?: string;
}

export function StatusDisplay({ status, className }: StatusDisplayProps) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <TaskStatusIcon status={status} className="h-4 w-4 shrink-0" />
      <StatusLabel status={status} />
    </div>
  );
}
