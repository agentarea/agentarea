import type { GlyphShape } from "@kit/components/glyphs";
import { PRIORITIES, STATUSES, type Priority, type Status } from "@shared/tasks";

export const STATUS_META: Record<Status, { label: string; color: string; glyph: GlyphShape; progress?: number }> = {
  backlog: { label: "Backlog", color: "var(--status-backlog)", glyph: "planned" },
  todo: { label: "Todo", color: "var(--status-todo)", glyph: "open" },
  in_progress: { label: "In progress", color: "var(--status-in_progress)", glyph: "open", progress: 0.5 },
  in_review: { label: "In review", color: "var(--status-in_review)", glyph: "open", progress: 0.75 },
  done: { label: "Done", color: "var(--status-done)", glyph: "done" },
  canceled: { label: "Canceled", color: "var(--status-canceled)", glyph: "canceled" },
};

export const PRIORITY_META: Record<Priority, { label: string }> = {
  urgent: { label: "Urgent" },
  high: { label: "High" },
  medium: { label: "Medium" },
  low: { label: "Low" },
  none: { label: "No priority" },
};

export const statusRank = (status: Status) => STATUSES.indexOf(status);
export const priorityRank = (priority: Priority) => PRIORITIES.indexOf(priority);
