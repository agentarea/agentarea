import { useTranslations } from "next-intl";
import { InfoPanelHeader } from "@/components/InfoPanel";
import { TaskStatus } from "@/components/TaskStatus";
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

  return (
    <InfoPanelHeader
      label={t("agentTask")}
      title={task.description || t("untitledTask")}
      right={
        <div className="flex items-center gap-2">
          <TaskStatus status={currentStatus} />
        </div>
      }
    />
  );
}
