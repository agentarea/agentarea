import type { ReactNode } from "react";
import { TaskStatus, useTaskStatusLabel } from "@/components/TaskStatus";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import Link from "@/components/WorkspaceLink";

/**
 * One task as a row of an overview section card: status marker, title, an
 * optional sub-line, then time and cost on the right. Shared by the agent and
 * member overviews.
 */
export function OverviewTaskRow({
  task,
  timeText,
  costText,
  sub,
  hideStatus = false,
}: {
  task: { id: string; status: string; description?: string | null };
  timeText: string;
  costText: string;
  /** A second line under the title, e.g. the agent that ran it. */
  sub?: ReactNode;
  /** Keep the marker for screen readers only, e.g. under a "Running" group. */
  hideStatus?: boolean;
}) {
  const status = String(task.status ?? "unknown");
  const label = useTaskStatusLabel(status);
  const title = task.description || task.id;

  return (
    <Link href={`/tasks/${task.id}`} className="block">
      <InteractiveListRow
        className="px-[15px] py-[11px]"
        dividerClassName="border-b border-border/60"
        contentClassName="gap-3"
        start={
          hideStatus ? (
            <span className="sr-only">{label}</span>
          ) : (
            <TaskStatus status={status} caption="never" className="shrink-0" />
          )
        }
        end={
          <span className="flex items-center gap-3 text-[11.5px] text-muted-foreground">
            <span className="whitespace-nowrap">{timeText}</span>
            <span className="w-[46px] text-right tabular-nums">{costText}</span>
          </span>
        }
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12.5px] font-medium">{title}</div>
          {sub != null && (
            <div className="mt-px truncate text-[11px] text-muted-foreground">
              {sub}
            </div>
          )}
        </div>
      </InteractiveListRow>
    </Link>
  );
}
