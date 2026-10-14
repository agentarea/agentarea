import { LabelChip } from "@kit/components/chip";
import { ListEmpty, ListFrame, ListGroup, ListRow, ListRowNote } from "@kit/components/list";
import { PersonAvatar } from "@kit/components/person-avatar";
import { STATUSES } from "@shared/tasks";
import { Fragment } from "react";
import { PriorityIcon } from "@/components/priority-icon";
import { StatusIcon } from "@/components/status-icon";
import { byPriority } from "@/lib/board";
import { STATUS_META } from "@/lib/meta";
import { DueDate } from "./issue-card";
import { NewIssueForm } from "./new-issue-form";
import type { BoardViewProps } from "./types";

/** The same rows as the board, as one table grouped by status. */
export function IssueList(props: BoardViewProps) {
  const { snapshot, tasks, labelColors, saving, notes, composing, onCompose, onOpen, onCreate } = props;
  const groups = STATUSES.map((status) => ({
    status,
    rows: tasks.filter((t) => t.status === status).toSorted(byPriority),
  })).filter((group) => group.rows.length > 0 || composing === group.status);

  if (groups.length === 0) return <ListEmpty>No issues match.</ListEmpty>;

  return (
    <ListFrame>
      {groups.map(({ status, rows }) => (
        <ListGroup
          key={status}
          title={STATUS_META[status].label}
          glyph={<StatusIcon status={status} />}
          count={rows.length}
          addLabel={`New issue in ${STATUS_META[status].label}`}
          onAdd={() => onCompose(composing === status ? null : status)}
        >
          {composing === status && (
            <div className="border-b p-2">
              <NewIssueForm snapshot={snapshot} status={status} onCreate={onCreate} onClose={() => onCompose(null)} />
            </div>
          )}
          {rows.map((task) => (
            <Fragment key={task.id}>
              <ListRow saving={saving[task.id] ?? false} onOpen={() => onOpen(task)}>
                <PriorityIcon priority={task.priority} />
                <span className="text-muted-foreground hidden w-14 shrink-0 font-mono text-[11px] sm:inline">
                  {task.key}
                </span>
                <StatusIcon status={task.status} />
                <span className="min-w-0 flex-1 truncate">
                  <span className="text-muted-foreground mr-1.5 font-mono text-[11px] sm:hidden">{task.key}</span>
                  {task.title}
                </span>
                <span className="hidden shrink-0 items-center gap-1 md:flex">
                  {task.labels.slice(0, 2).map((label) => (
                    <LabelChip key={label} name={label} color={labelColors.get(label)} />
                  ))}
                </span>
                <DueDate task={task} now={snapshot.now} className="hidden min-[440px]:inline-flex" />
                <PersonAvatar person={task.assignee} />
              </ListRow>
              <ListRowNote>{notes[task.id]}</ListRowNote>
            </Fragment>
          ))}
        </ListGroup>
      ))}
    </ListFrame>
  );
}
