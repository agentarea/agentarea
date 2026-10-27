import type { EventType } from "@kit/events/protocol.ts";
import { PERSON_KINDS, type PersonKind } from "../shared/tasks.ts";

export const TASK_ASSIGNED = "task.assigned";

type AssignedArgs = { assignee?: string; project?: string; assigneeKind?: PersonKind };

const ARGUMENTS = ["assignee", "project", "assigneeKind"];

const personSchema = {
  type: "object",
  properties: { handle: { type: "string" }, name: { type: "string" }, kind: { enum: [...PERSON_KINDS] } },
  required: ["handle", "name", "kind"],
};

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
      project: { type: "string", description: 'Project key, e.g. "OPS"' },
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
      project: { type: "object", properties: { key: { type: "string" }, name: { type: "string" } }, required: ["key", "name"] },
      assignee: personSchema,
      assignedBy: personSchema,
    },
    required: ["key", "title", "status", "project", "assignee", "assignedBy"],
  },
  parseArguments(raw) {
    for (const key of Object.keys(raw)) {
      if (!ARGUMENTS.includes(key)) throw new Error(`unknown argument ${JSON.stringify(key)}; use ${ARGUMENTS.join(", ")}`);
    }
    const text = (key: string) => {
      const value = raw[key];
      if (value === undefined) return undefined;
      if (typeof value !== "string" || !value.trim()) throw new Error(`${key} must be a non-empty string`);
      return value.trim().replace(/^@/, "").toLowerCase();
    };
    const kind = raw.assigneeKind;
    if (kind !== undefined && !PERSON_KINDS.includes(kind as PersonKind)) throw new Error(`assigneeKind is ${PERSON_KINDS.join(" or ")}`);
    return { assignee: text("assignee"), project: text("project"), assigneeKind: kind as PersonKind | undefined };
  },
  admits(args, data) {
    const assignee = data.assignee as { handle: string; kind: PersonKind };
    const project = data.project as { key: string };
    return (
      (args.assignee === undefined || assignee.handle.toLowerCase() === args.assignee) &&
      (args.project === undefined || project.key.toLowerCase() === args.project) &&
      (args.assigneeKind === undefined || assignee.kind === args.assigneeKind)
    );
  },
};

export const EVENT_TYPES = [taskAssigned] as EventType<never>[];
