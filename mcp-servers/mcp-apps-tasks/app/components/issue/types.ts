import type { TaskDetail } from "@shared/schema";

export type Field = "title" | "status" | "priority" | "assignee" | "due" | "comment" | "link" | "refresh";

/** Per-control state, so each one reports its own progress and errors in place. */
export type FieldState = {
  busy: Partial<Record<Field, boolean>>;
  notes: Partial<Record<Field, string>>;
};

export type IssueActions = {
  /** Saves one field through `update_task`; `apply` is the optimistic change. */
  onUpdate: (field: Field, args: Record<string, unknown>, apply: (card: TaskDetail) => TaskDetail) => void;
  onComment: (body: string) => Promise<boolean>;
  onOpenIssue: (key: string) => void;
  onOpenBoard: () => void;
  onRefresh: () => void;
};
