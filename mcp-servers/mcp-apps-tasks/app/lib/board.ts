import type { TaskDetail, TaskRow } from "@shared/schema";
import { priorityRank } from "./meta";

/** Column order: most urgent first, then most recently updated. */
export const byPriority = (a: TaskRow, b: TaskRow) =>
  priorityRank(a.priority) - priorityRank(b.priority) || b.updatedAt.localeCompare(a.updatedAt);

/** The board's text filter: key, title, labels or assignee. */
export function matchesText(task: TaskRow, text: string): boolean {
  const needle = text.trim().toLowerCase();
  if (!needle) return true;
  return (
    task.key.toLowerCase().includes(needle) ||
    task.title.toLowerCase().includes(needle) ||
    task.labels.some((label) => label.includes(needle)) ||
    (task.assignee?.name.toLowerCase().includes(needle) ?? false)
  );
}

/** The row fields of a full issue, as the board keeps them. */
export function rowOf(detail: TaskDetail): TaskRow {
  const {
    asOf: _asOf,
    now: _now,
    generatedAt: _generatedAt,
    description: _description,
    projectName: _projectName,
    creator: _creator,
    parent: _parent,
    children: _children,
    commentList: _commentList,
    activity: _activity,
    people: _people,
    labelPalette: _labelPalette,
    ...row
  } = detail;
  return row;
}
