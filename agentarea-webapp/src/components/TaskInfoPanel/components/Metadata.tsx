import { useTranslations } from "next-intl";
import { Activity, Bot, Hash } from "lucide-react";
import { Task } from "../types";
import {
  InfoPanelField,
  InfoPanelSection,
  InfoPanelValueBox,
} from "@/components/InfoPanel";
import { CopyableText } from "@/components/ui/copyable-text";

interface MetadataProps {
  task: Task;
}

export default function Metadata({ task }: MetadataProps) {
  const t = useTranslations("TaskInfoPanel");

  return (
    <InfoPanelSection title={t("metadata")} contentClassName="space-y-3 text-xs">
      <InfoPanelField label={t("taskId")} icon={Hash}>
        <CopyableText 
          text={task.id} 
          displayValue={task.id.split('-')[0]} 
        />
      </InfoPanelField>

      <InfoPanelField label={t("agent")} icon={Bot}>
        <InfoPanelValueBox>
          {task.agent_name || `${t("agent")} ${task.agent_id}`}
        </InfoPanelValueBox>
      </InfoPanelField>

      {task.execution_id && (
        <InfoPanelField label={t("executionId")} icon={Activity}>
          <CopyableText 
            text={task.execution_id} 
            displayValue={task.execution_id.split('-').slice(0, 2).join('-')}
          />
        </InfoPanelField>
      )}
    </InfoPanelSection>
  );
}
