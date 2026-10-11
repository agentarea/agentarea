export const STATUSES = ["backlog", "todo", "in_progress", "in_review", "done", "canceled"] as const;
export type Status = (typeof STATUSES)[number];

/** Statuses an issue no longer moves out of on its own: it never counts as overdue. */
export const CLOSED_STATUSES: readonly Status[] = ["done", "canceled"];

export const PRIORITIES = ["urgent", "high", "medium", "low", "none"] as const;
export type Priority = (typeof PRIORITIES)[number];

export const PERSON_KINDS = ["human", "agent"] as const;
export type PersonKind = (typeof PERSON_KINDS)[number];

export const LABEL_COLORS = ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "gray"] as const;
export type LabelColor = (typeof LABEL_COLORS)[number];

export const ACTIVITY_KINDS = [
  "created",
  "title",
  "description",
  "status",
  "priority",
  "assignee",
  "due",
  "labels",
  "estimate",
  "parent",
] as const;
export type ActivityKind = (typeof ACTIVITY_KINDS)[number];

// ---------------------------------------------------------------------------
// Dataset: the tracker as the server works with it; stored as tables in the app's sqlite database.
// ---------------------------------------------------------------------------

export type Person = {
  id: string;
  name: string;
  /** Short unique handle, e.g. "maya"; tools accept it in place of the id. */
  handle: string;
  kind: PersonKind;
  title: string;
};

export type Project = {
  id: string;
  /** Issue key prefix, e.g. "WEB". */
  key: string;
  name: string;
  description: string;
  leadId: string;
  /** Number the next issue in this project gets. */
  nextNumber: number;
};

export type Label = { name: string; color: LabelColor };

export type Comment = {
  id: string;
  authorId: string;
  body: string;
  createdAt: string;
};

/**
 * One recorded change. `from` and `to` hold the raw stored values (a person
 * id for assignee, an issue id for parent, a comma list for labels).
 */
export type Activity = {
  id: string;
  actorId: string;
  at: string;
  kind: ActivityKind;
  from: string | null;
  to: string | null;
};

export type Issue = {
  id: string;
  projectId: string;
  number: number;
  /** "<project key>-<number>", e.g. "WEB-12". */
  key: string;
  title: string;
  /** Markdown. */
  description: string;
  status: Status;
  priority: Priority;
  assigneeId: string | null;
  labels: string[];
  /** Calendar date, "YYYY-MM-DD". */
  dueDate: string | null;
  estimate: number | null;
  parentId: string | null;
  creatorId: string;
  createdAt: string;
  updatedAt: string;
  comments: Comment[];
  activity: Activity[];
};

export type TasksData = {
  version: 1;
  /** Reference "now" of the seeded dataset; the live clock takes over once it passes. */
  asOf: string;
  /** Person whose tracker this is: the default actor when a tool call names none. */
  viewerId: string;
  people: Person[];
  projects: Project[];
  labels: Label[];
  issues: Issue[];
};
