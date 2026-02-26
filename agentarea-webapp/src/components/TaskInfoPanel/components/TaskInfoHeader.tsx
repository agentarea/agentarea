import { Badge } from "@/components/ui/badge";
import { Task } from "../types";

interface TaskInfoHeaderProps {
  task: Task;
  currentStatus: string;
}

export default function TaskInfoHeader({ task, currentStatus }: TaskInfoHeaderProps) {
  const statusVariant =
    currentStatus === "running"
      ? "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200"
      : currentStatus === "completed" || currentStatus === "success"
        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200"
        : currentStatus === "paused"
          ? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200"
          : "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200";

  return (
    <div className="flex items-start justify-between gap-3 px-3 pb-3 pt-3">
      <div className="space-y-1">
        <div className="text-xs uppercase tracking-wide text-muted-foreground font-normal">
          Agent Task
        </div>
        <h3 className="line-clamp-2 text-sm font-semibold text-foreground">
          {task.description || "Untitled task"}
        </h3>
      </div>
      <Badge
        className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${statusVariant}`}
      >
        {currentStatus.charAt(0).toUpperCase() + currentStatus.slice(1)}
      </Badge>
    </div>
  );
}
