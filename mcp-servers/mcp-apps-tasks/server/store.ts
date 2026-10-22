import type { Database } from "bun:sqlite";
import { insertRows, readRows, syncRows, type Rows } from "@kit/store/rows.ts";
import {
  PERSON_KINDS,
  type Activity,
  type ActivityKind,
  type Comment,
  type Issue,
  type Person,
  type PersonKind,
  type Priority,
  type Project,
  type Status,
  type TasksData,
} from "../shared/tasks.ts";
import { fromRows, TABLES, toRows } from "./db.ts";

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const HANDLE = /^[a-z0-9][a-z0-9._-]{0,31}$/;
const PROJECT_KEY = /^[A-Z][A-Z0-9]{1,9}$/;

export type PersonFields = { name: string; handle: string; kind?: PersonKind; title?: string };
export type ProjectFields = { key: string; name: string; description?: string; lead: string };
export type TrackerSetup = { people: PersonFields[]; viewer: string; projects: ProjectFields[] };

export type IssueFields = {
  title?: string;
  description?: string;
  status?: Status;
  priority?: Priority;
  assignee?: string | null;
  labels?: string[];
  due?: string | null;
  estimate?: number | null;
  parent?: string | null;
};

/**
 * The tracker as it stands in one store transaction (or read): loaded from the
 * database's rows, changed in memory, and written back by `save`, which
 * touches only the rows that changed.
 */
export class TasksStore {
  readonly #rows: Rows;
  #seq: Record<"iss" | "cmt" | "act", number>;

  private constructor(
    readonly data: TasksData,
    rows: Rows,
  ) {
    this.#rows = rows;
    const max = (ids: string[]) => Math.max(0, ...ids.map((id) => Number.parseInt(id.split("_")[1] ?? "0", 10) || 0));
    this.#seq = {
      iss: max(data.issues.map((i) => i.id)),
      cmt: max(data.issues.flatMap((i) => i.comments.map((c) => c.id))),
      act: max(data.issues.flatMap((i) => i.activity.map((a) => a.id))),
    };
  }

  static load(db: Database): TasksStore {
    const rows = readRows(db, TABLES);
    return new TasksStore(fromRows(rows), rows);
  }

  /** The tracker as stored, or null while its storage holds no tracker yet. */
  static loadIfSetUp(db: Database): TasksStore | null {
    return db.query("SELECT 1 FROM tracker").get() ? TasksStore.load(db) : null;
  }

  /** Writes a new tracker into empty storage: its people, whose tracker it is, and its first projects. */
  static setup(db: Database, setup: TrackerSetup): TasksStore {
    if (db.query("SELECT 1 FROM tracker").get()) throw new Error("The tracker is already set up; add people and projects with add_person and create_project.");
    const empty: TasksData = { version: 1, asOf: new Date().toISOString(), viewerId: "", people: [], projects: [], labels: [], issues: [] };
    const store = new TasksStore(empty, {});
    for (const person of setup.people) store.addPerson(person);
    empty.viewerId = store.person(setup.viewer).id;
    for (const project of setup.projects) store.createProject(project);
    insertRows(db, TABLES, toRows(empty));
    return store;
  }

  /** Writes what changed since `load` into `db`, inside the caller's transaction. */
  save(db: Database): void {
    syncRows(db, TABLES, this.#rows, toRows(this.data));
  }

  /** The tracker's clock: never earlier than the dataset's own `asOf`. */
  now(): string {
    return new Date(Math.max(Date.now(), Date.parse(this.data.asOf))).toISOString();
  }

  #id(kind: "iss" | "cmt" | "act"): string {
    return `${kind}_${String(++this.#seq[kind]).padStart(3, "0")}`;
  }

  person(ref: string): Person {
    const needle = ref.trim().replace(/^@/, "").toLowerCase();
    if (needle === "me") {
      const viewer = this.data.people.find((p) => p.id === this.data.viewerId);
      if (!viewer) throw new Error('"me" means nobody until the tracker is set up; name the person by handle.');
      return viewer;
    }
    const person = this.data.people.find(
      (p) => p.id === needle || p.handle.toLowerCase() === needle || p.name.toLowerCase() === needle,
    );
    if (!person) {
      const known = this.data.people.map((p) => `${p.handle} (${p.name}, ${p.kind})`).join(", ");
      throw new Error(`No person "${ref}". Use a person id, handle or name: ${known}.`);
    }
    return person;
  }

  project(ref: string): Project {
    const needle = ref.trim().toLowerCase();
    const project = this.data.projects.find((p) => p.key.toLowerCase() === needle || p.id === needle);
    if (!project) {
      const known = this.data.projects.map((p) => `${p.key} (${p.name})`).join(", ");
      throw new Error(`No project "${ref}". Projects: ${known}.`);
    }
    return project;
  }

  issue(ref: string): Issue {
    const needle = ref.trim().toUpperCase();
    const issue = this.data.issues.find((i) => i.key === needle || i.id.toUpperCase() === needle);
    if (!issue) {
      throw new Error(`No issue "${ref}". Issue keys look like "WEB-12"; call list_tasks to find one.`);
    }
    return issue;
  }

  #record(issue: Issue, actorId: string, at: string, kind: ActivityKind, from: string | null, to: string | null) {
    const entry: Activity = { id: this.#id("act"), actorId, at, kind, from, to };
    issue.activity.push(entry);
  }

  #labels(labels: string[]): string[] {
    const names: string[] = [];
    for (const raw of labels) {
      const name = raw.trim().toLowerCase();
      if (!name || names.includes(name)) continue;
      if (!this.data.labels.some((l) => l.name === name)) this.data.labels.push({ name, color: "gray" });
      names.push(name);
    }
    return names;
  }

  #parent(issue: Pick<Issue, "id" | "projectId">, ref: string): Issue {
    const parent = this.issue(ref);
    if (parent.projectId !== issue.projectId) {
      throw new Error(`${parent.key} is in another project; a sub-issue must share its parent's project.`);
    }
    for (let at: Issue | undefined = parent; at; at = this.data.issues.find((i) => i.id === at!.parentId)) {
      if (at.id === issue.id) throw new Error(`${parent.key} cannot be the parent: that would make a cycle.`);
    }
    return parent;
  }

  create(projectRef: string, fields: IssueFields & { title: string }, actorRef?: string): Issue {
    const project = this.project(projectRef);
    const actor = actorRef ? this.person(actorRef) : this.person("me");
    const title = fields.title.trim();
    if (!title) throw new Error("An issue needs a title.");
    const assigneeId = fields.assignee ? this.person(fields.assignee).id : null;
    const dueDate = fields.due ? checkDate(fields.due) : null;
    const estimate = fields.estimate == null ? null : checkEstimate(fields.estimate);
    const parentId = fields.parent ? this.#parent({ id: "", projectId: project.id }, fields.parent).id : null;
    const at = this.now();
    const issue: Issue = {
      id: this.#id("iss"),
      projectId: project.id,
      number: project.nextNumber,
      key: `${project.key}-${project.nextNumber}`,
      title,
      description: fields.description?.trim() ?? "",
      status: fields.status ?? "todo",
      priority: fields.priority ?? "none",
      assigneeId,
      labels: this.#labels(fields.labels ?? []),
      dueDate,
      estimate,
      parentId,
      creatorId: actor.id,
      createdAt: at,
      updatedAt: at,
      comments: [],
      activity: [],
    };
    project.nextNumber += 1;
    this.#record(issue, actor.id, at, "created", null, issue.status);
    this.data.issues.push(issue);
    return issue;
  }

  /** Applies only what differs from the stored issue; each real change is one activity entry. */
  update(ref: string, fields: IssueFields, actorRef?: string): { issue: Issue; changed: ActivityKind[] } {
    const issue = this.issue(ref);
    const actor = actorRef ? this.person(actorRef) : this.person("me");
    const at = this.now();
    const changed: ActivityKind[] = [];
    const apply = <K extends keyof Issue>(kind: ActivityKind, key: K, next: Issue[K], show = (v: Issue[K]) => v as string | null) => {
      const previous = issue[key];
      if (JSON.stringify(previous) === JSON.stringify(next)) return;
      issue[key] = next;
      changed.push(kind);
      this.#record(issue, actor.id, at, kind, show(previous), show(next));
    };

    // Resolve every field first: an invalid one fails the call before anything changes.
    const title = fields.title?.trim();
    if (title === "") throw new Error("The title cannot be empty.");
    const assigneeId = fields.assignee == null ? fields.assignee : this.person(fields.assignee).id;
    const dueDate = fields.due == null ? fields.due : checkDate(fields.due);
    const estimate = fields.estimate == null ? fields.estimate : checkEstimate(fields.estimate);
    const parentId = fields.parent == null ? fields.parent : this.#parent(issue, fields.parent).id;
    const labels = fields.labels && this.#labels(fields.labels);

    if (title !== undefined) apply("title", "title", title);
    if (fields.description !== undefined) apply("description", "description", fields.description.trim(), () => null);
    if (fields.status !== undefined) apply("status", "status", fields.status);
    if (fields.priority !== undefined) apply("priority", "priority", fields.priority);
    if (assigneeId !== undefined) apply("assignee", "assigneeId", assigneeId);
    if (labels !== undefined) apply("labels", "labels", labels, (v) => (v.length ? v.join(", ") : null));
    if (dueDate !== undefined) apply("due", "dueDate", dueDate);
    if (estimate !== undefined) apply("estimate", "estimate", estimate, (v) => (v === null ? null : String(v)));
    if (parentId !== undefined) apply("parent", "parentId", parentId);
    if (changed.length) issue.updatedAt = at;
    return { issue, changed };
  }

  addPerson(fields: PersonFields): Person {
    const name = fields.name.trim();
    if (!name) throw new Error("A person needs a name.");
    const handle = fields.handle.trim().replace(/^@/, "").toLowerCase();
    if (!HANDLE.test(handle)) throw new Error(`"${fields.handle}" is not a handle; use up to 32 latin letters, digits, ".", "_" or "-".`);
    if (handle === "me" || handle === "unassigned") throw new Error(`"${handle}" is reserved; pick another handle.`);
    if (this.data.people.some((p) => p.handle.toLowerCase() === handle)) throw new Error(`The handle "${handle}" is taken.`);
    const kind = fields.kind ?? "human";
    if (!PERSON_KINDS.includes(kind)) throw new Error(`A person is ${PERSON_KINDS.join(" or ")}.`);
    const next = Math.max(0, ...this.data.people.map((p) => Number.parseInt(p.id.split("_")[1] ?? "0", 10) || 0)) + 1;
    const person: Person = { id: `usr_${String(next).padStart(2, "0")}`, name, handle, kind, title: fields.title?.trim() ?? "" };
    this.data.people.push(person);
    return person;
  }

  createProject(fields: ProjectFields): Project {
    const key = fields.key.trim().toUpperCase();
    if (!PROJECT_KEY.test(key)) throw new Error(`"${fields.key}" is not a project key; use 2-10 latin letters and digits, starting with a letter.`);
    if (this.data.projects.some((p) => p.key === key)) throw new Error(`The project key ${key} is taken.`);
    const name = fields.name.trim();
    if (!name) throw new Error("A project needs a name.");
    const project: Project = {
      id: `prj_${key.toLowerCase()}`,
      key,
      name,
      description: fields.description?.trim() ?? "",
      leadId: this.person(fields.lead).id,
      nextNumber: 1,
    };
    this.data.projects.push(project);
    return project;
  }

  comment(ref: string, body: string, authorRef?: string): { issue: Issue; comment: Comment } {
    const issue = this.issue(ref);
    const author = authorRef ? this.person(authorRef) : this.person("me");
    const text = body.trim();
    if (!text) throw new Error("A comment needs a body.");
    const comment: Comment = { id: this.#id("cmt"), authorId: author.id, body: text, createdAt: this.now() };
    issue.comments.push(comment);
    issue.updatedAt = comment.createdAt;
    return { issue, comment };
  }

}

function checkDate(value: string): string {
  if (!DATE.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) {
    throw new Error(`"${value}" is not a date; use YYYY-MM-DD.`);
  }
  return value;
}

function checkEstimate(value: number): number {
  if (!Number.isFinite(value) || value < 0) throw new Error("An estimate is a non-negative number of points.");
  return value;
}
