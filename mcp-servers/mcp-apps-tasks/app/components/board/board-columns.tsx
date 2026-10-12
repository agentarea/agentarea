import { BoardColumn, BoardScroller, useBoardDrag } from "@kit/components/board";
import { STATUSES, type Status } from "@shared/tasks";
import { StatusIcon } from "@/components/status-icon";
import { byPriority } from "@/lib/board";
import { STATUS_META } from "@/lib/meta";
import { IssueCard } from "./issue-card";
import { NewIssueForm } from "./new-issue-form";
import type { BoardViewProps } from "./types";

/** One column per status. Cards drag between columns; dropping one changes its status. */
export function BoardColumns(props: BoardViewProps) {
  const { snapshot, tasks, labelColors, saving, notes, composing, onCompose, onOpen, onMove, onCreate } = props;
  const drag = useBoardDrag<Status>((taskId, status) => {
    const task = tasks.find((t) => t.id === taskId);
    if (task && task.status !== status) onMove(task, status);
  });

  return (
    <BoardScroller>
      {STATUSES.map((status) => {
        const column = tasks.filter((t) => t.status === status).toSorted(byPriority);
        return (
          <BoardColumn
            key={status}
            title={STATUS_META[status].label}
            glyph={<StatusIcon status={status} />}
            count={column.length}
            addLabel={`New issue in ${STATUS_META[status].label}`}
            onAdd={() => onCompose(composing === status ? null : status)}
            drop={drag.column(status)}
            empty={column.length === 0 && composing !== status ? "No issues" : undefined}
          >
            {composing === status && (
              <NewIssueForm snapshot={snapshot} status={status} onCreate={onCreate} onClose={() => onCompose(null)} />
            )}
            {column.map((task) => (
              <IssueCard
                key={task.id}
                task={task}
                now={snapshot.now}
                labelColors={labelColors}
                saving={saving[task.id] ?? false}
                note={notes[task.id]}
                onOpen={() => onOpen(task)}
                {...drag.card(task.id)}
              />
            ))}
          </BoardColumn>
        );
      })}
    </BoardScroller>
  );
}
