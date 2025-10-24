import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type StatusBadgeProps = {
  status: string;
  className?: string;
  variant?: "default" | "agent" | "task" | "custom";
};

// Функция для определения цвета badge на основе статуса
const getStatusBadgeVariant = (status: string, variant: string = "default") => {
  const statusLower = status.toLowerCase();

  // Логика для агентов
  if (variant === "agent") {
    switch (statusLower) {
      case "online":
      case "running":
      case "completed":
      case "active":
        return "success";
      case "busy":
        return "yellow";
      case "paused":
        return "orange";
      case "offline":
      case "error":
      case "failed":
        return "destructive";
      case "stopped":
      case "idle":
      case "inactive":
      default:
        return "secondary";
    }
  }

  // Логика для задач
  if (variant === "task") {
    switch (statusLower) {
      case "completed":
      case "success":
      case "done":
        return "success";
      case "in_progress":
      case "running":
      case "processing":
        return "blue";
      case "pending":
      case "waiting":
        return "yellow";
      case "failed":
      case "error":
      case "cancelled":
        return "destructive";
      case "paused":
      case "suspended":
        return "orange";
      default:
        return "secondary";
    }
  }

  // Общая логика по умолчанию
  switch (statusLower) {
    case "success":
    case "completed":
    case "done":
    case "active":
    case "online":
      return "success";
    case "warning":
    case "pending":
    case "waiting":
      return "yellow";
    case "error":
    case "failed":
    case "cancelled":
      return "destructive";
    case "info":
    case "processing":
    case "in_progress":
      return "blue";
    case "paused":
    case "suspended":
      return "orange";
    case "inactive":
    case "offline":
    case "stopped":
      return "secondary";
    default:
      return "secondary";
  }
};

export function StatusBadge({
  status,
  className,
  variant = "default",
}: StatusBadgeProps) {
  return (
    <Badge
      variant={getStatusBadgeVariant(status, variant)}
      className={cn("text-xs", className)}
    >
      {status}
    </Badge>
  );
}
