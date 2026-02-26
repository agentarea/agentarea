import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Task } from "../types";
import Section from "./Section";

interface QuickActionsProps {
  task: Task;
}

export default function QuickActions({ task }: QuickActionsProps) {
  return (
    <Section title="Quick actions" contentClassName="space-y-1.5 text-xs">
        {task.execution_id && (
          <Link
            href={`/tasks/${task.id}?tab=events`}
            className="flex items-center justify-between rounded-md px-2.5 py-1.5 text-[13px] text-foreground hover:bg-muted/80"
          >
            <span>View task events</span>
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          </Link>
        )}
        <Link
          href={`/agents/${task.agent_id}`}
          className="flex items-center justify-between rounded-md px-2.5 py-1.5 text-[13px] text-foreground hover:bg-muted/80"
        >
          <span>Open agent details</span>
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        </Link>
        {task.result && (
          <button
            type="button"
            className="flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-[13px] text-foreground/80 hover:bg-muted/80"
          >
            <span>Inspect task result</span>
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        )}
    </Section>
  );
}
