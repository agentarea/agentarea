import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { InfoPanelHeader } from "@/components/InfoPanel";
import { Task } from "../types";

interface TaskInfoHeaderProps {
  task: Task;
  currentStatus: string;
}

export default function TaskInfoHeader({ task, currentStatus }: TaskInfoHeaderProps) {
  const t = useTranslations("TaskInfoPanel");
  const statusVariant =
    currentStatus === "running"
      ? "blue"
      : currentStatus === "completed" || currentStatus === "success"
        ? "emerald"
        : currentStatus === "paused"
          ? "amber"
          : "rose";

  return (
    <InfoPanelHeader
      label={t("agentTask")}
      title={task.description || t("untitledTask")}
      right={
        <Badge variant={statusVariant as any} size="sm">
          {currentStatus.charAt(0).toUpperCase() + currentStatus.slice(1)}
        </Badge>
      }
    />
  );
}
