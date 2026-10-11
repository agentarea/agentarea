import type {
  ActivityEntry,
  BoardSnapshot,
  PersonRef,
  TaskDetail,
  TaskList,
  TaskRow,
} from "../shared/schema.ts";
import {
  CLOSED_STATUSES,
  PRIORITIES,
  STATUSES,
  type Issue,
  type Person,
  type Priority,
  type Status,
  type TasksData,
} from "../shared/tasks.ts";
import type { TasksStore } from "./store.ts";

export const STATUS_LABEL: Record<Status, string> = {
  backlog: "Backlog",
  todo: "Todo",
  in_progress: "In progress",
  in_review: "In review",
  done: "Done",
  canceled: "Canceled",
};

export const PRIORITY_LABEL: Record<Priority, string> = {
  urgent: "Urgent",
  high: "High",
  medium: "Medium",
  low: "Low",
  none: "No priority",
};

export type TaskFilter = {
  project?: string;
  status?: Status[];
  assignee?: string;
  label?: string;
  priority?: Priority[];
  overdue?: boolean;
  query?: string;
};

const personRef = (p: Person): PersonRef => ({ id: p.id, name: p.name, handle: p.handle, kind: p.kind });

/** Lookups shared by every view of one request. */
class Index {
  readonly people: Map<string, Person>;
  readonly issues: Map<string, Issue>;
  readonly children = new Map<string, Issue[]>();
  readonly today: string;

  constructor(
    readonly data: TasksData,
    readonly now: string,
  ) {
    this.people = new Map(data.people.map((p) => [p.id, p]));
    this.issues = new Map(data.issues.map((i) => [i.id, i]));
    for (const issue of data.issues) {
      if (issue.parentId) this.children.set(issue.parentId, [...(this.children.get(issue.parentId) ?? []), issue]);
    }
    this.today = now.slice(0, 10);
  }

  overdue(issue: Issue): boolean {
    return issue.dueDate !== null && issue.dueDate < this.today && !CLOSED_STATUSES.includes(issue.status);
  }

  ref(personId: string): PersonRef {
    return personRef(this.people.get(personId)!);
  }

  row(issue: Issue): TaskRow {
    const children = this.children.get(issue.id) ?? [];
    return {
      id: issue.id,
      key: issue.key,
      project: issue.key.split("-")[0],
      title: issue.title,
      status: issue.status,
      priority: issue.priority,
      assignee: issue.assigneeId ? this.ref(issue.assigneeId) : null,
      labels: issue.labels,
      dueDate: issue.dueDate,
      overdue: this.overdue(issue),
      estimate: issue.estimate,
      parentKey: issue.parentId ? (this.issues.get(issue.parentId)?.key ?? null) : null,
      subIssues: { total: children.length, done: children.filter((c) => c.status === "done").length },
      comments: issue.comments.length,
      createdAt: issue.createdAt,
      updatedAt: issue.updatedAt,
    };
  }
}

const statusRank = (s: Status) => STATUSES.indexOf(s);
const priorityRank = (p: Priority) => PRIORITIES.indexOf(p);

function byBoardOrder(a: Issue, b: Issue): number {
  return (
    statusRank(a.status) - statusRank(b.status) ||
    priorityRank(a.priority) - priorityRank(b.priority) ||
    b.updatedAt.localeCompare(a.updatedAt)
  );
}

/** Issues matching `filter`, in board order. Throws for an unknown project or person. */
function select(store: TasksStore, filter: TaskFilter, index: Index): Issue[] {
  const project = filter.project ? store.project(filter.project) : null;
  const assignee =
    filter.assignee === undefined ? undefined : filter.assignee === "unassigned" ? null : store.person(filter.assignee).id;
  const label = filter.label?.trim().toLowerCase();
  const query = filter.query?.trim().toLowerCase();
  return store.data.issues
    .filter(
      (issue) =>
        (!project || issue.projectId === project.id) &&
        (!filter.status?.length || filter.status.includes(issue.status)) &&
        (assignee === undefined || issue.assigneeId === assignee) &&
        (!label || issue.labels.includes(label)) &&
        (!filter.priority?.length || filter.priority.includes(issue.priority)) &&
        (filter.overdue === undefined || index.overdue(issue) === filter.overdue) &&
        (!query ||
          issue.key.toLowerCase() === query ||
          issue.title.toLowerCase().includes(query) ||
          issue.description.toLowerCase().includes(query)),
    )
    .toSorted(byBoardOrder);
}

export function buildSnapshot(store: TasksStore, filter: { project?: string; assignee?: string }): BoardSnapshot {
  const { data } = store;
  const now = store.now();
  const index = new Index(data, now);
  const issues = select(store, filter, index);
  const counts = Object.fromEntries(STATUSES.map((s) => [s, 0])) as Record<Status, number>;
  for (const issue of issues) counts[issue.status] += 1;
  return {
    asOf: data.asOf,
    now,
    generatedAt: new Date().toISOString(),
    viewer: index.ref(data.viewerId),
    project: filter.project ? store.project(filter.project).key : null,
    assignee:
      filter.assignee === undefined ? null : filter.assignee === "unassigned" ? "unassigned" : store.person(filter.assignee).id,
    projects: data.projects.map((p) => ({
      id: p.id,
      key: p.key,
      name: p.name,
      description: p.description,
      open: data.issues.filter((i) => i.projectId === p.id && !CLOSED_STATUSES.includes(i.status)).length,
    })),
    people: data.people.map((p) => ({ ...personRef(p), title: p.title })),
    labels: data.labels,
    counts,
    tasks: issues.map((issue) => index.row(issue)),
  };
}

export function listTasks(store: TasksStore, filter: TaskFilter, limit: number): TaskList {
  const index = new Index(store.data, store.now());
  const issues = select(store, filter, index);
  const tasks = issues.slice(0, limit).map((issue) => index.row(issue));
  return { total: issues.length, returned: tasks.length, tasks };
}

export function buildDetail(store: TasksStore, ref: string): TaskDetail {
  const { data } = store;
  const issue = store.issue(ref);
  const now = store.now();
  const index = new Index(data, now);
  const project = data.projects.find((p) => p.id === issue.projectId)!;
  const parent = issue.parentId ? index.issues.get(issue.parentId) : undefined;
  const show = (kind: ActivityEntry["kind"], value: string | null): string | null => {
    if (value === null) return null;
    if (kind === "assignee") return index.people.get(value)?.name ?? value;
    if (kind === "parent") return index.issues.get(value)?.key ?? value;
    return value;
  };
  return {
    ...index.row(issue),
    asOf: data.asOf,
    now,
    generatedAt: new Date().toISOString(),
    description: issue.description,
    projectName: project.name,
    creator: index.ref(issue.creatorId),
    parent: parent ? { key: parent.key, title: parent.title, status: parent.status } : null,
    children: (index.children.get(issue.id) ?? []).toSorted(byBoardOrder).map((c) => index.row(c)),
    commentList: issue.comments.map((c) => ({
      id: c.id,
      author: index.ref(c.authorId),
      body: c.body,
      createdAt: c.createdAt,
    })),
    activity: issue.activity.map((a) => ({
      id: a.id,
      actor: index.ref(a.actorId),
      at: a.at,
      kind: a.kind,
      from: show(a.kind, a.from),
      to: show(a.kind, a.to),
    })),
    people: data.people.map((p) => ({ ...personRef(p), title: p.title })),
    labelPalette: data.labels,
  };
}

// ---------------------------------------------------------------------------
// Text content: what a model reads next to the structured result.
// ---------------------------------------------------------------------------

/** "WEB-12 [In progress · High] Title — @maya, due 2026-10-03 (overdue)" */
export const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

export function rowLine(row: TaskRow): string {
  const who = row.assignee ? `@${row.assignee.handle}${row.assignee.kind === "agent" ? " (agent)" : ""}` : "unassigned";
  const due = row.dueDate ? `, due ${row.dueDate}${row.overdue ? " (overdue)" : ""}` : "";
  const labels = row.labels.length ? ` {${row.labels.join(", ")}}` : "";
  return `${row.key} [${STATUS_LABEL[row.status]} · ${PRIORITY_LABEL[row.priority]}] ${row.title} — ${who}${due}${labels}`;
}

export function summarizeSnapshot(snapshot: BoardSnapshot): string {
  const scope = snapshot.project
    ? `${snapshot.project} · ${snapshot.projects.find((p) => p.key === snapshot.project)?.name ?? ""}`
    : "All projects";
  const who =
    snapshot.assignee === null
      ? ""
      : snapshot.assignee === "unassigned"
        ? ", unassigned only"
        : `, assigned to ${snapshot.people.find((p) => p.id === snapshot.assignee)?.name}`;
  const counts = STATUSES.map((s) => `${snapshot.counts[s]} ${STATUS_LABEL[s].toLowerCase()}`).join(", ");
  const overdue = snapshot.tasks.filter((t) => t.overdue);
  const urgent = snapshot.tasks.filter((t) => t.priority === "urgent" && !CLOSED_STATUSES.includes(t.status));
  return [
    `${scope}${who}: ${plural(snapshot.tasks.length, "issue")} — ${counts}.`,
    overdue.length ? `Overdue (${overdue.length}): ${overdue.map((t) => `${t.key} due ${t.dueDate}`).join(", ")}.` : "Nothing overdue.",
    urgent.length ? `Open urgent: ${urgent.map((t) => `${t.key} ${t.title}`).join("; ")}.` : "",
    "The board is shown to the user. Use list_tasks for filtered rows and show_task for one issue.",
  ]
    .filter(Boolean)
    .join("\n");
}

export function summarizeDetail(detail: TaskDetail): string {
  const lines = [
    rowLine(detail),
    `${detail.projectName}; created by ${detail.creator.name} ${detail.createdAt.slice(0, 10)}, updated ${detail.updatedAt.slice(0, 10)}.`,
  ];
  if (detail.estimate !== null) lines.push(`Estimate: ${detail.estimate} points.`);
  if (detail.parent) lines.push(`Sub-issue of ${detail.parent.key} “${detail.parent.title}”.`);
  if (detail.children.length) {
    lines.push(`Sub-issues (${detail.subIssues.done}/${detail.subIssues.total} done): ${detail.children.map((c) => `${c.key} ${STATUS_LABEL[c.status]}`).join(", ")}.`);
  }
  if (detail.description) lines.push("", detail.description);
  if (detail.commentList.length) {
    lines.push("", `Comments (${detail.commentList.length}):`);
    for (const c of detail.commentList.slice(-5)) lines.push(`- ${c.author.name} (${c.createdAt.slice(0, 10)}): ${c.body}`);
  }
  return lines.join("\n");
}

export function summarizeList(list: TaskList): string {
  if (!list.total) return "No issues match these filters.";
  const head =
    list.total > list.returned
      ? `${plural(list.total, "issue")} match; showing the first ${list.returned}:`
      : `${plural(list.total, "issue")}:`;
  return [head, ...list.tasks.map(rowLine)].join("\n");
}
