import { useTranslations } from "next-intl";
import { InfoPanelHeader } from "@/components/InfoPanel";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { TaskWithAgent } from "@/lib/api";
import { getTaskStatusPresentation } from "@/lib/status";
import { Task } from "../types";

interface TaskInfoHeaderProps {
  task: Task;
  currentStatus: string;
}

export default function TaskInfoHeader({
  task,
  currentStatus,
}: TaskInfoHeaderProps) {
  const t = useTranslations("TaskInfoPanel");
  const tStatus = useTranslations("TasksPage.status");
  const status = currentStatus as TaskWithAgent["status"];
  const presentation = getTaskStatusPresentation(status);
  const label = presentation.labelKey
    ? tStatus(presentation.labelKey)
    : presentation.label;

  return (
    <InfoPanelHeader
      label={t("agentTask")}
      title={task.description || t("untitledTask")}
      right={
        <div className="flex items-center gap-2">
          <StatusIndicator
            size="sm"
            tone={presentation.tone}
            pulse={presentation.pulse}
          >
            {label}
          </StatusIndicator>
        </div>
      }
    />
  );
}
