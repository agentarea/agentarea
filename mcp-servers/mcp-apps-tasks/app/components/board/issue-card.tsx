import { BoardCard, CardNote } from "@kit/components/board";
import { Chip, LabelChip } from "@kit/components/chip";
import { PersonAvatar } from "@kit/components/person-avatar";
import { cn } from "@kit/lib/utils";
import type { TaskRow } from "@shared/schema";
import type { LabelColor } from "@shared/tasks";
import { CalendarClock, GitFork } from "lucide-react";
import type { DragEvent } from "react";
import { PriorityIcon } from "@/components/priority-icon";
import { formatDay } from "@/lib/format";

export function DueDate({ task, now, className }: { task: TaskRow; now: string; className?: string }) {
  if (!task.dueDate) return null;
  return (
    <Chip
      tone={task.overdue ? "danger" : "neutral"}
      className={cn("tabular", className)}
      title={task.overdue ? `Overdue: was due ${task.dueDate}` : `Due ${task.dueDate}`}
    >
      <CalendarClock />
      {formatDay(task.dueDate, now)}
    </Chip>
  );
}

export function IssueCard({
  task,
  now,
  labelColors,
  saving,
  dragging,
  note,
  onOpen,
  onDragStart,
  onDragEnd,
}: {
  task: TaskRow;
  now: string;
  labelColors: Map<string, LabelColor>;
  saving: boolean;
  dragging: boolean;
  note: string | undefined;
  onOpen: () => void;
  onDragStart: (event: DragEvent) => void;
  onDragEnd: () => void;
}) {
  return (
    <BoardCard
      label={`${task.key} ${task.title}`}
      saving={saving}
      dragging={dragging}
      onOpen={onOpen}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      <div className="flex items-center gap-1.5">
        <PriorityIcon priority={task.priority} />
        <span className="text-muted-foreground font-mono text-[11px]">{task.key}</span>
        {task.parentKey && (
          <span
            className="text-subtle-foreground inline-flex items-center gap-0.5 truncate font-mono text-[10px]"
            title={`Sub-issue of ${task.parentKey}`}
          >
            <GitFork className="size-2.5" />
            {task.parentKey}
          </span>
        )}
        <span className="ml-auto">
          <PersonAvatar person={task.assignee} />
        </span>
      </div>
      <p className="mt-1.5 line-clamp-2 text-[13px] leading-snug font-medium">{task.title}</p>
      {(task.dueDate || task.labels.length > 0 || task.subIssues.total > 0) && (
        <div className="mt-2 flex flex-wrap items-center gap-1">
          <DueDate task={task} now={now} />
          {task.subIssues.total > 0 && (
            <Chip className="tabular">
              {task.subIssues.done}/{task.subIssues.total}
            </Chip>
          )}
          {task.labels.map((label) => (
            <LabelChip key={label} name={label} color={labelColors.get(label)} />
          ))}
        </div>
      )}
      <CardNote>{note}</CardNote>
    </BoardCard>
  );
}
