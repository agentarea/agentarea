import { Activity, Bot, Hash } from "lucide-react";
import { Task } from "../types";
import Section from "./Section";

interface MetadataProps {
  task: Task;
}

export default function Metadata({ task }: MetadataProps) {
  return (
    <Section title="Metadata" contentClassName="space-y-1.5 text-[11px] text-muted-foreground">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-1.5">
            <Hash className="h-3.5 w-3.5 text-primary" />
            <span>Task ID</span>
          </div>
          <span className="truncate font-mono text-[11px] text-foreground">
            {task.id}
          </span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-1.5">
            <Bot className="h-3.5 w-3.5 text-primary" />
            <span>Agent</span>
          </div>
          <span className="truncate text-[11px] text-foreground">
            {task.agent_name || `Agent ${task.agent_id}`}
          </span>
        </div>
        {task.execution_id && (
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-primary" />
              <span>Execution ID</span>
            </div>
            <span className="truncate font-mono text-[11px] text-foreground">
              {task.execution_id}
            </span>
          </div>
        )}
    </Section>
  );
}
