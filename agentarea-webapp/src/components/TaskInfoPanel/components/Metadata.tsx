import { useTranslations } from "next-intl";
import Link from "next/link";
import { Activity, GitFork, Hash } from "lucide-react";
import { AgentLink } from "@/components/AgentIdentity";
import {
  InfoPanelField,
  InfoPanelSection,
  InfoPanelValueBox,
} from "@/components/InfoPanel";
import { CopyableText } from "@/components/ui/copyable-text";
import { Task } from "../types";

interface MetadataProps {
  task: Task;
}

export default function Metadata({ task }: MetadataProps) {
  const t = useTranslations("TaskInfoPanel");
  const parentTaskId = task.parameters?.parent_task_id as string | undefined;
  const isDelegation = task.parameters?.source === "agent_delegation";

  return (
    <InfoPanelSection
      title={t("metadata")}
      contentClassName="space-y-3 text-xs"
    >
      <InfoPanelField label={t("taskId")} icon={Hash}>
        <CopyableText text={task.id} displayValue={task.id.split("-")[0]} />
      </InfoPanelField>

      <InfoPanelField label={t("agent")}>
        <InfoPanelValueBox className="p-0">
          <AgentLink
            agent={{
              id: task.agent_id,
              name: task.agent_name || t("agent"),
            }}
            size="xs"
            className="w-full p-1.5"
            nameClassName="text-xs"
          />
        </InfoPanelValueBox>
      </InfoPanelField>

      {task.execution_id && (
        <InfoPanelField label={t("executionId")} icon={Activity}>
          <CopyableText
            text={task.execution_id}
            displayValue={task.execution_id.split("-").slice(0, 2).join("-")}
          />
        </InfoPanelField>
      )}

      {isDelegation && parentTaskId && (
        <InfoPanelField label={t("parentTask")} icon={GitFork}>
          <Link
            href={`/tasks/${parentTaskId}`}
            className="text-xs text-primary hover:underline"
          >
            {parentTaskId.split("-")[0]}
          </Link>
        </InfoPanelField>
      )}
    </InfoPanelSection>
  );
}
