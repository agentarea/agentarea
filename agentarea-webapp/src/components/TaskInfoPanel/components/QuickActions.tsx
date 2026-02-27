import { useTranslations } from "next-intl";
import { Task } from "../types";
import Section from "./Section";
import ActionLink from "./ActionLink";

interface QuickActionsProps {
  task: Task;
}

export default function QuickActions({ task }: QuickActionsProps) {
  const t = useTranslations("TaskInfoPanel");

  return (
    <Section title={t("quickActions")} contentClassName="space-y-1.5 text-xs">
      {task.execution_id && (
        <ActionLink href={`/tasks/${task.id}/events`}>
          {t("viewTaskEvents")}
        </ActionLink>
      )}
      <ActionLink href={`/agents/${task.agent_id}`}>
        {t("openAgentDetails")}
      </ActionLink>
    </Section>
  );
}
