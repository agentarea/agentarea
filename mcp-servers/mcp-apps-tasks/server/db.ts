import type { Database } from "bun:sqlite";
import { insertRows, type Row, type Rows, type Table } from "@kit/store/rows.ts";
import { EVENT_LOG_MIGRATION } from "@kit/events/log.ts";
import type { Migration } from "@kit/store/store.ts";
import demo from "../data/tasks.json" with { type: "json" };
import type { Activity, ActivityKind, Issue, LabelColor, PersonKind, Priority, Status, TasksData } from "../shared/tasks.ts";

export const DB_FILE = "tasks.sqlite";

/** Migration `i` brings the schema to version `i + 1`. Never edit one that has shipped: append. */
export const MIGRATIONS: Migration[] = [
  (db) =>
    db.run(`
      CREATE TABLE people (
        id     TEXT PRIMARY KEY,
        name   TEXT NOT NULL,
        handle TEXT NOT NULL UNIQUE COLLATE NOCASE,
        kind   TEXT NOT NULL CHECK (kind IN ('human', 'agent')),
        title  TEXT NOT NULL
      );
      CREATE TABLE tracker (
        id        INTEGER PRIMARY KEY CHECK (id = 1),
        as_of     TEXT NOT NULL,
        viewer_id TEXT NOT NULL REFERENCES people (id)
      );
      CREATE TABLE projects (
        id          TEXT PRIMARY KEY,
        key         TEXT NOT NULL UNIQUE COLLATE NOCASE,
        name        TEXT NOT NULL,
        description TEXT NOT NULL,
        lead_id     TEXT NOT NULL REFERENCES people (id),
        next_number INTEGER NOT NULL
      );
      CREATE TABLE labels (
        name  TEXT PRIMARY KEY,
        color TEXT NOT NULL CHECK (color IN ('red', 'orange', 'yellow', 'green', 'teal', 'blue', 'purple', 'pink', 'gray'))
      );
      CREATE TABLE issues (
        id          TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL REFERENCES projects (id),
        number      INTEGER NOT NULL,
        key         TEXT NOT NULL UNIQUE,
        title       TEXT NOT NULL,
        description TEXT NOT NULL,
        status      TEXT NOT NULL CHECK (status IN ('backlog', 'todo', 'in_progress', 'in_review', 'done', 'canceled')),
        priority    TEXT NOT NULL CHECK (priority IN ('urgent', 'high', 'medium', 'low', 'none')),
        assignee_id TEXT REFERENCES people (id),
        due_date    TEXT,
        estimate    REAL,
        parent_id   TEXT REFERENCES issues (id),
        creator_id  TEXT NOT NULL REFERENCES people (id),
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        UNIQUE (project_id, number)
      );
      CREATE INDEX issues_status ON issues (status);
      CREATE INDEX issues_assignee ON issues (assignee_id);
      CREATE INDEX issues_parent ON issues (parent_id);
      CREATE TABLE issue_labels (
        issue_id TEXT NOT NULL REFERENCES issues (id),
        position INTEGER NOT NULL,
        label    TEXT NOT NULL REFERENCES labels (name),
        PRIMARY KEY (issue_id, position)
      );
      CREATE INDEX issue_labels_label ON issue_labels (label);
      CREATE TABLE comments (
        id         TEXT PRIMARY KEY,
        issue_id   TEXT NOT NULL REFERENCES issues (id),
        author_id  TEXT NOT NULL REFERENCES people (id),
        body       TEXT NOT NULL,
        created_at TEXT NOT NULL
      );
      CREATE INDEX comments_issue ON comments (issue_id);
      CREATE TABLE issue_activity (
        id         TEXT PRIMARY KEY,
        issue_id   TEXT NOT NULL REFERENCES issues (id),
        actor_id   TEXT NOT NULL REFERENCES people (id),
        at         TEXT NOT NULL,
        kind       TEXT NOT NULL CHECK (kind IN ('created', 'title', 'description', 'status', 'priority', 'assignee', 'due', 'labels', 'estimate', 'parent')),
        from_value TEXT,
        to_value   TEXT
      );
      CREATE INDEX issue_activity_issue ON issue_activity (issue_id);
    `),
  // Outgoing MCP Events (task.assigned), served by events/poll.
  EVENT_LOG_MIGRATION,
  // People tied to the platform identity the caller context names.
  (db) =>
    db.run(`
      ALTER TABLE people ADD COLUMN platform_id TEXT;
      CREATE UNIQUE INDEX people_platform_id ON people (platform_id) WHERE platform_id IS NOT NULL;
    `),
];

export const TABLES: Table[] = [
  { name: "people", columns: ["id", "name", "handle", "kind", "title", "platform_id"], key: ["id"] },
  { name: "tracker", columns: ["id", "as_of", "viewer_id"], key: ["id"] },
  { name: "projects", columns: ["id", "key", "name", "description", "lead_id", "next_number"], key: ["id"] },
  { name: "labels", columns: ["name", "color"], key: ["name"] },
  {
    name: "issues",
    columns: [
      "id", "project_id", "number", "key", "title", "description", "status", "priority", "assignee_id",
      "due_date", "estimate", "parent_id", "creator_id", "created_at", "updated_at",
    ],
    key: ["id"],
  },
  { name: "issue_labels", columns: ["issue_id", "position", "label"], key: ["issue_id", "position"], orderBy: "issue_id, position" },
  { name: "comments", columns: ["id", "issue_id", "author_id", "body", "created_at"], key: ["id"] },
  { name: "issue_activity", columns: ["id", "issue_id", "actor_id", "at", "kind", "from_value", "to_value"], key: ["id"] },
];

export function toRows(data: TasksData): Rows {
  return {
    people: data.people.map((p) => ({
      id: p.id, name: p.name, handle: p.handle, kind: p.kind, title: p.title, platform_id: p.platformId ?? null,
    })),
    tracker: [{ id: 1, as_of: data.asOf, viewer_id: data.viewerId }],
    projects: data.projects.map((p) => ({
      id: p.id, key: p.key, name: p.name, description: p.description, lead_id: p.leadId, next_number: p.nextNumber,
    })),
    labels: data.labels.map((l) => ({ name: l.name, color: l.color })),
    issues: data.issues.map((i) => ({
      id: i.id, project_id: i.projectId, number: i.number, key: i.key, title: i.title, description: i.description,
      status: i.status, priority: i.priority, assignee_id: i.assigneeId, due_date: i.dueDate, estimate: i.estimate,
      parent_id: i.parentId, creator_id: i.creatorId, created_at: i.createdAt, updated_at: i.updatedAt,
    })),
    issue_labels: data.issues.flatMap((i) => i.labels.map((label, position) => ({ issue_id: i.id, position, label }))),
    comments: data.issues.flatMap((i) =>
      i.comments.map((c) => ({ id: c.id, issue_id: i.id, author_id: c.authorId, body: c.body, created_at: c.createdAt })),
    ),
    issue_activity: data.issues.flatMap((i) =>
      i.activity.map((a) => ({
        id: a.id, issue_id: i.id, actor_id: a.actorId, at: a.at, kind: a.kind, from_value: a.from, to_value: a.to,
      })),
    ),
  };
}

const str = (v: Row[string]) => v as string;
const opt = (v: Row[string]) => v as string | null;

function groupBy(rows: Row[], column: string): Map<string, Row[]> {
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    const key = str(row[column]);
    const group = groups.get(key);
    if (group) group.push(row);
    else groups.set(key, [row]);
  }
  return groups;
}

export function fromRows(rows: Rows): TasksData {
  const tracker = rows.tracker[0];
  if (!tracker) {
    throw new Error(
      "The tracker is empty: its storage holds no people or projects yet; set it up with setup_tracker.",
    );
  }
  const labels = groupBy(rows.issue_labels, "issue_id");
  const comments = groupBy(rows.comments, "issue_id");
  const activity = groupBy(rows.issue_activity, "issue_id");
  return {
    version: 1,
    asOf: str(tracker.as_of),
    viewerId: str(tracker.viewer_id),
    people: rows.people.map((p) => ({
      id: str(p.id), name: str(p.name), handle: str(p.handle), kind: p.kind as PersonKind, title: str(p.title),
      platformId: opt(p.platform_id),
    })),
    projects: rows.projects.map((p) => ({
      id: str(p.id), key: str(p.key), name: str(p.name), description: str(p.description), leadId: str(p.lead_id),
      nextNumber: p.next_number as number,
    })),
    labels: rows.labels.map((l) => ({ name: str(l.name), color: l.color as LabelColor })),
    issues: rows.issues.map((i): Issue => {
      const id = str(i.id);
      return {
        id,
        projectId: str(i.project_id),
        number: i.number as number,
        key: str(i.key),
        title: str(i.title),
        description: str(i.description),
        status: i.status as Status,
        priority: i.priority as Priority,
        assigneeId: opt(i.assignee_id),
        labels: (labels.get(id) ?? []).map((l) => str(l.label)),
        dueDate: opt(i.due_date),
        estimate: i.estimate as number | null,
        parentId: opt(i.parent_id),
        creatorId: str(i.creator_id),
        createdAt: str(i.created_at),
        updatedAt: str(i.updated_at),
        comments: (comments.get(id) ?? []).map((c) => ({
          id: str(c.id), authorId: str(c.author_id), body: str(c.body), createdAt: str(c.created_at),
        })),
        activity: (activity.get(id) ?? []).map(
          (a): Activity => ({
            id: str(a.id), actorId: str(a.actor_id), at: str(a.at), kind: a.kind as ActivityKind,
            from: opt(a.from_value), to: opt(a.to_value),
          }),
        ),
      };
    }),
  };
}

/** The demo tracker from `data/tasks.json` (generated by `bun run seed`). */
export const seedDemo: Migration = (db: Database) => insertRows(db, TABLES, toRows(demo as unknown as TasksData));
