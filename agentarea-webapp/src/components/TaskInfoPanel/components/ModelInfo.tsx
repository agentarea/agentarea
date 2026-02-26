import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Task } from "../types";
import Section from "./Section";

interface ModelInfoProps {
  task: Task;
}

export default function ModelInfo({ task }: ModelInfoProps) {
  return (
    <Section title="Agent model" contentClassName="space-y-4 text-xs">
        <div className="space-y-1">
          <div className="text-sm font-semibold text-foreground">
            {task.agent_name || `Agent ${task.agent_id}`}
          </div>
          {task.agent_description && (
            <p className="text-[11px] text-muted-foreground">
              {task.agent_description}
            </p>
          )}
        </div>

        <div className="space-y-1.5 pt-1">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Model configuration
          </div>
          <p className="text-[11px] text-muted-foreground">
            View full model settings, tools, and usage metrics for this agent.
          </p>
          <Link
            href={`/agents/${task.agent_id}`}
            className="inline-flex w-full items-center justify-between rounded-md border border-border/70 bg-background px-3 py-1.5 text-[13px] text-foreground hover:bg-muted/70"
          >
            <span>Open agent details</span>
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          </Link>
        </div>
    </Section>
  );
}
