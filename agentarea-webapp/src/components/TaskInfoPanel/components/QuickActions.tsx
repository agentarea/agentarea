import { Task } from "../types";
import Section from "./Section";
import ActionLink from "./ActionLink";

interface QuickActionsProps {
  task: Task;
}

export default function QuickActions({ task }: QuickActionsProps) {
  return (
    <Section title="Quick actions" contentClassName="space-y-1.5 text-xs">
        {task.execution_id && (
          <ActionLink href={`/tasks/${task.id}?tab=events`}>
            View task events
          </ActionLink>
        )}
        <ActionLink href={`/agents/${task.agent_id}`}>
          Open agent details
        </ActionLink>
        {task.result && (
          <ActionLink onClick={() => {}}>
            Inspect task result
          </ActionLink>
        )}
    </Section>
  );
}
