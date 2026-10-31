import type { EventType } from "@kit/events/protocol.ts";
import { PERSON_KINDS, STATUSES, type PersonKind, type Status } from "../shared/tasks.ts";

export const TASK_ASSIGNED = "task.assigned";
export const TASK_CREATED = "task.created";
export const TASK_STATUS_CHANGED = "task.status_changed";
export const TASK_COMMENTED = "task.commented";

type Person = { handle: string; kind: PersonKind };

/**
 * Checks a subscription's arguments: only `names`, each a non-empty string,
 * handles and keys lowercased without a leading "@", and an argument listed in
 * `choices` one of its values.
 */
function parseArgs(raw: Record<string, unknown>, names: string[], choices: Record<string, readonly string[]> = {}) {
  for (const key of Object.keys(raw)) {
    if (!names.includes(key)) throw new Error(`unknown argument ${JSON.stringify(key)}; use ${names.join(", ")}`);
  }
  const args: Record<string, string | undefined> = {};
  for (const key of names) {
    const value = raw[key];
    if (value === undefined) continue;
    const allowed = choices[key];
    if (allowed) {
      if (!allowed.includes(value as string)) throw new Error(`${key} is ${allowed.join(" or ")}`);
      args[key] = value as string;
      continue;
    }
    if (typeof value !== "string" || !value.trim()) throw new Error(`${key} must be a non-empty string`);
    args[key] = value.trim().replace(/^@/, "").toLowerCase();
  }
  return args;
}

const inProject = (project: string | undefined, data: Record<string, unknown>) =>
  project === undefined || (data.project as { key: string }).key.toLowerCase() === project;

/** `assignee` is a handle, or "unassigned" for an issue nobody has. */
const assignedTo = (assignee: string | undefined, data: Record<string, unknown>) => {
  if (assignee === undefined) return true;
  const person = data.assignee as Person | null;
  return assignee === "unassigned" ? person === null : person?.handle.toLowerCase() === assignee;
};

const ofKind = (kind: PersonKind | undefined, person: unknown) => kind === undefined || (person as Person).kind === kind;

const personSchema = {
  type: "object",
  properties: { handle: { type: "string" }, name: { type: "string" }, kind: { enum: [...PERSON_KINDS] } },
  required: ["handle", "name", "kind"],
};

const projectSchema = { type: "object", properties: { key: { type: "string" }, name: { type: "string" } }, required: ["key", "name"] };

/** The issue as every task event carries it. */
const issueProperties = {
  key: { type: "string" },
  title: { type: "string" },
  description: { type: "string" },
  status: { enum: [...STATUSES] },
  priority: { type: "string" },
  due: { type: ["string", "null"] },
  project: projectSchema,
  assignee: { anyOf: [personSchema, { type: "null" }] },
};

const projectArg = { type: "string", description: 'Project key, e.g. "OPS"' };
const assigneeArg = { type: "string", description: 'Assignee handle, e.g. "ops-bot", or "unassigned"' };
const kindArg = (whose: string) => ({ enum: [...PERSON_KINDS], description: `Only ${whose} of this kind` });

type AssignedArgs = { assignee?: string; project?: string; assigneeKind?: PersonKind };

const ARGUMENTS = ["assignee", "project", "assigneeKind"];

/**
 * An issue got an assignee, on create or on update. A subscriber narrows it to
 * one assignee, one project or one kind of assignee; an agent's trigger
 * subscribes with its own handle.
 */
export const taskAssigned: EventType<AssignedArgs> = {
  name: TASK_ASSIGNED,
  title: "Task assigned",
  description: "An issue was assigned to someone, when it was created or later. Narrow it by assignee handle, project key or assignee kind.",
  inputSchema: {
    type: "object",
    properties: {
      assignee: { type: "string", description: 'Assignee handle, e.g. "ops-bot"' },
      project: projectArg,
      assigneeKind: { enum: [...PERSON_KINDS], description: "Only assignees of this kind" },
    },
    additionalProperties: false,
  },
  payloadSchema: {
    type: "object",
    properties: {
      key: { type: "string" },
      title: { type: "string" },
      description: { type: "string" },
      status: { type: "string" },
      priority: { type: "string" },
      due: { type: ["string", "null"] },
      project: projectSchema,
      assignee: personSchema,
      assignedBy: personSchema,
    },
    required: ["key", "title", "status", "project", "assignee", "assignedBy"],
  },
  parseArguments(raw) {
    const args = parseArgs(raw, ARGUMENTS, { assigneeKind: PERSON_KINDS });
    return { assignee: args.assignee, project: args.project, assigneeKind: args.assigneeKind as PersonKind | undefined };
  },
  admits(args, data) {
    const assignee = data.assignee as Person;
    return (
      (args.assignee === undefined || assignee.handle.toLowerCase() === args.assignee) &&
      inProject(args.project, data) &&
      ofKind(args.assigneeKind, assignee)
    );
  },
};

type CreatedArgs = { project?: string; assignee?: string; creatorKind?: PersonKind };

/** Every new issue, assigned or not. An agent narrows it to its project, or to issues a person (not an agent) opened. */
export const taskCreated: EventType<CreatedArgs> = {
  name: TASK_CREATED,
  title: "Task created",
  description:
    "A new issue was created. Narrow it by project key, assignee handle (or \"unassigned\") or the kind of person who created it. " +
    "createdBy is the caller, or the actor the call named.",
  inputSchema: {
    type: "object",
    properties: { project: projectArg, assignee: assigneeArg, creatorKind: kindArg("creators") },
    additionalProperties: false,
  },
  payloadSchema: {
    type: "object",
    properties: { ...issueProperties, createdBy: personSchema },
    required: ["key", "title", "status", "project", "assignee", "createdBy"],
  },
  parseArguments(raw) {
    const args = parseArgs(raw, ["project", "assignee", "creatorKind"], { creatorKind: PERSON_KINDS });
    return { project: args.project, assignee: args.assignee, creatorKind: args.creatorKind as PersonKind | undefined };
  },
  admits(args, data) {
    return inProject(args.project, data) && assignedTo(args.assignee, data) && ofKind(args.creatorKind, data.createdBy);
  },
};

type StatusChangedArgs = { project?: string; status?: Status; assignee?: string };

/** An issue moved to another status: in review, done, canceled, back to todo. */
export const taskStatusChanged: EventType<StatusChangedArgs> = {
  name: TASK_STATUS_CHANGED,
  title: "Task status changed",
  description:
    "An issue moved from one status to another. Narrow it by project key, the new status or the assignee handle (or \"unassigned\"). " +
    "changedBy is the caller, or the actor the call named.",
  inputSchema: {
    type: "object",
    properties: {
      project: projectArg,
      status: { enum: [...STATUSES], description: "Only moves into this status" },
      assignee: assigneeArg,
    },
    additionalProperties: false,
  },
  payloadSchema: {
    type: "object",
    properties: { ...issueProperties, from: { enum: [...STATUSES] }, to: { enum: [...STATUSES] }, changedBy: personSchema },
    required: ["key", "title", "status", "project", "assignee", "from", "to", "changedBy"],
  },
  parseArguments(raw) {
    const args = parseArgs(raw, ["project", "status", "assignee"], { status: STATUSES });
    return { project: args.project, status: args.status as Status | undefined, assignee: args.assignee };
  },
  admits(args, data) {
    return inProject(args.project, data) && (args.status === undefined || data.to === args.status) && assignedTo(args.assignee, data);
  },
};

type CommentedArgs = { project?: string; assignee?: string; authorKind?: PersonKind };

/** A comment on an issue. An agent subscribes to human comments only, so its own replies never wake it. */
export const taskCommented: EventType<CommentedArgs> = {
  name: TASK_COMMENTED,
  title: "Task commented",
  description:
    "Someone commented on an issue. Narrow it by project key, the issue's assignee handle (or \"unassigned\") or the kind of author: " +
    'authorKind "human" leaves out comments agents write.',
  inputSchema: {
    type: "object",
    properties: { project: projectArg, assignee: assigneeArg, authorKind: kindArg("comment authors") },
    additionalProperties: false,
  },
  payloadSchema: {
    type: "object",
    properties: {
      key: { type: "string" },
      title: { type: "string" },
      status: { enum: [...STATUSES] },
      project: projectSchema,
      assignee: issueProperties.assignee,
      comment: { type: "object", properties: { id: { type: "string" }, body: { type: "string" } }, required: ["id", "body"] },
      author: personSchema,
    },
    required: ["key", "title", "status", "project", "assignee", "comment", "author"],
  },
  parseArguments(raw) {
    const args = parseArgs(raw, ["project", "assignee", "authorKind"], { authorKind: PERSON_KINDS });
    return { project: args.project, assignee: args.assignee, authorKind: args.authorKind as PersonKind | undefined };
  },
  admits(args, data) {
    return inProject(args.project, data) && assignedTo(args.assignee, data) && ofKind(args.authorKind, data.author);
  },
};

export const EVENT_TYPES = [taskAssigned, taskCreated, taskStatusChanged, taskCommented] as EventType<never>[];
