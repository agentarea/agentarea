import { useTranslations } from "next-intl";
import { InfoPanelHeader } from "@/components/InfoPanel";
import { TaskStatusIcon } from "@/components/TaskStatusIcon";
import { TaskWithAgent } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Task } from "../types";

interface TaskInfoHeaderProps {
  task: Task;
  currentStatus: string;
}

export default function TaskInfoHeader({ task, currentStatus }: TaskInfoHeaderProps) {
  const t = useTranslations("TaskInfoPanel");
  const tStatus = useTranslations("TasksPage.status");
  const status = currentStatus as TaskWithAgent['status'];

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

  const colorClass = {
    completed: "text-green-600 dark:text-green-500",
    success: "text-green-600 dark:text-green-500",
    failed: "text-red-600 dark:text-red-500",
    error: "text-red-600 dark:text-red-500",
    running: "text-primary",
    in_progress: "text-primary",
    pending: "text-muted-foreground",
    paused: "text-muted-foreground",
  }[status] || "text-muted-foreground";

  return (
    <InfoPanelHeader
      label={t("agentTask")}
      title={task.description || t("untitledTask")}
      right={
        <div className="flex items-center gap-2">
          <TaskStatusIcon status={status} className="h-4 w-4 shrink-0" />
          <span className={cn("text-[10px] font-normal uppercase tracking-wider", colorClass)}>
            {label}
          </span>
        </div>
      }
    />
  );
}
