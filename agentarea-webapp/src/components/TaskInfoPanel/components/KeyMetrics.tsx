import { useTranslations } from "next-intl";
import { Clock } from "lucide-react";
import { TaskStatusIcon } from "@/components/ui/task-status-icon";
import { TaskWithAgent } from "@/lib/api";
import { cn } from "@/lib/utils";
import Section from "./Section";

interface KeyMetricsProps {
  currentStatus: string;
  isActive: boolean;
  executionTime: string;
  formattedStart: string;
  formattedEnd: string;
}

export default function KeyMetrics({
  currentStatus,
  isActive,
  executionTime,
  formattedStart,
  formattedEnd,
}: KeyMetricsProps) {
  const t = useTranslations("TaskInfoPanel");
  const tStatus = useTranslations("TasksPage.status");
  const status = currentStatus as TaskWithAgent["status"];

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

  const colorClass =
    {
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
    <Section
      title={t("keyMetrics")}
      contentClassName="text-xs grid grid-cols-1 md:grid-cols-1 lg:grid-cols-2 gap-3"
    >
      <div className="space-y-1">
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {t("status")}
        </div>
        <div className="flex items-center gap-2">
          <TaskStatusIcon status={status} className="h-4 w-4 shrink-0" />
          <span
            className={cn(
              "text-[11px] font-normal uppercase tracking-wider",
              colorClass
            )}
          >
            {label}
          </span>
        </div>
        <div className="text-[10px] text-muted-foreground">
          {isActive ? t("taskActive") : t("taskNotRunning")}
        </div>
      </div>

      <div className="space-y-1">
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {t("executionTime")}
        </div>
        <div className="text-[12px] font-normal text-foreground">
          {executionTime || "N/A"}
        </div>
        <div className="text-[10px] text-muted-foreground">
          {t("executionTimeDesc")}
        </div>
      </div>

      <div className="space-y-1">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          <Clock className="h-3 w-3 text-primary" />
          {t("started")}
        </div>
        <div className="text-[12px] font-normal text-foreground">
          {formattedStart}
        </div>
      </div>

      <div className="space-y-1">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          <Clock className="h-3 w-3 text-muted-foreground" />
          {t("ended")}
        </div>
        <div className="text-[12px] font-normal text-foreground">
          {formattedEnd}
        </div>
      </div>
    </Section>
  );
}
