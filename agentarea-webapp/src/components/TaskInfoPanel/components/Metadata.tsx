import { useTranslations } from "next-intl";
import { Activity, Bot, Hash } from "lucide-react";
import { Task } from "../types";
import Section from "./Section";

interface MetadataProps {
  task: Task;
}

export default function Metadata({ task }: MetadataProps) {
  const t = useTranslations("TaskInfoPanel");

  return (
    <Section title={t("metadata")} contentClassName="space-y-3 text-xs">
      <div className="space-y-1">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          <Hash className="h-3 w-3 text-primary" />
          {t("taskId")}
        </div>
        <div className="truncate font-mono text-xs text-foreground bg-muted/30 p-1.5 rounded-md border border-border/50">
          {task.id}
        </div>
      </div>

      <div className="space-y-1">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          <Bot className="h-3 w-3 text-primary" />
          {t("agent")}
        </div>
        <div className="truncate text-xs text-foreground bg-muted/30 p-1.5 rounded-md border border-border/50">
          {task.agent_name || `${t("agent")} ${task.agent_id}`}
        </div>
      </div>

      {task.execution_id && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Activity className="h-3 w-3 text-primary" />
            {t("executionId")}
          </div>
          <div className="truncate font-mono text-xs text-foreground bg-muted/30 p-1.5 rounded-md border border-border/50">
            {task.execution_id}
          </div>
        </div>
      )}
    </Section>
  );
}
