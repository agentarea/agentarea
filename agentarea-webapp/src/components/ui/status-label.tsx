"use client";

import { useTranslations } from "next-intl";
import { TaskWithAgent } from "@/lib/api";
import { cn } from "@/lib/utils";

type Status = TaskWithAgent["status"] | string;

interface StatusLabelProps {
  status: Status;
  className?: string;
}

const statusColors: Record<string, string> = {
  completed: "text-green-600 dark:text-green-500",
  success: "text-green-600 dark:text-green-500",
  failed: "text-red-600 dark:text-red-500",
  error: "text-red-600 dark:text-red-500",
  running: "text-primary",
  in_progress: "text-primary",
  pending: "text-muted-foreground",
  paused: "text-muted-foreground",
};

export function StatusLabel({ status, className }: StatusLabelProps) {
  const tStatus = useTranslations("TasksPage.status");

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

  const colorClass = statusColors[status] || "text-muted-foreground";

  return (
    <span
      className={cn(
        "text-[11px] font-normal uppercase tracking-wider",
        colorClass,
        className
      )}
    >
      {label}
    </span>
  );
}
