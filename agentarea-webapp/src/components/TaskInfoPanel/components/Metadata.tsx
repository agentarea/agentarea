import { useTranslations } from "next-intl";
import { Activity, Bot, Hash } from "lucide-react";
import { Task } from "../types";
import {
  InfoPanelField,
  InfoPanelSection,
  InfoPanelValueBox,
} from "@/components/InfoPanel";

interface MetadataProps {
  task: Task;
}

export default function Metadata({ task }: MetadataProps) {
  const t = useTranslations("TaskInfoPanel");

  return (
    <InfoPanelSection title={t("metadata")} contentClassName="space-y-3 text-xs">
      <InfoPanelField label={t("taskId")} icon={Hash}>
        <InfoPanelValueBox mono>{task.id}</InfoPanelValueBox>
      </InfoPanelField>

      <InfoPanelField label={t("agent")} icon={Bot}>
        <InfoPanelValueBox>
          {task.agent_name || `${t("agent")} ${task.agent_id}`}
        </InfoPanelValueBox>
      </InfoPanelField>

      {task.execution_id && (
        <InfoPanelField label={t("executionId")} icon={Activity}>
          <InfoPanelValueBox mono>{task.execution_id}</InfoPanelValueBox>
        </InfoPanelField>
      )}
    </InfoPanelSection>
  );
}
