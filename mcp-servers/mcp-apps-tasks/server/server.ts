import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import { installEvents } from "@kit/events/install.ts";
import type { AppStore } from "@kit/store/store.ts";
import { McpServer, ProtocolError, type ReadResourceResult } from "@modelcontextprotocol/server";
import fs from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { PERSON_KINDS } from "../shared/tasks.ts";
import {
  addedCommentSchema,
  boardSnapshotSchema,
  prioritySchema,
  statusSchema,
  taskDetailSchema,
  taskListSchema,
  type AddedComment,
} from "../shared/schema.ts";
import { EVENT_TYPES } from "./events.ts";
import { TasksStore } from "./store.ts";
import {
  buildDetail,
  buildSnapshot,
  listTasks,
  plural,
  PRIORITY_LABEL,
  STATUS_LABEL,
  summarizeDetail,
  summarizeList,
  summarizeSnapshot,
} from "./views.ts";

export const BOARD_URI = "ui://tasks/board.html";
export const ISSUE_URI = "ui://tasks/issue.html";

/** Built views, one single-file HTML each, inside `appDir`. */
const VIEWS = [
  { uri: BOARD_URI, name: "Task board", file: "board.html", description: "Issue board by status, with a grouped list view" },
  { uri: ISSUE_URI, name: "Issue", file: "issue.html", description: "One issue: properties, sub-issues, comments and activity" },
] as const;
export const VIEW_FILES = VIEWS.map((view) => view.file);

const LIST_LIMIT = 50;

const show = (kind: string, value: string | null) => {
  if (value === null) return "none";
  if (kind === "status") return STATUS_LABEL[value as keyof typeof STATUS_LABEL] ?? value;
  if (kind === "priority") return PRIORITY_LABEL[value as keyof typeof PRIORITY_LABEL] ?? value;
  return value;
};

/**
 * The app is the view resources plus their tools. The data is not part of
 * it: it lives in `app`, the instance's store; every tool call is one read or
 * one transaction there. `current` is the tracker as of this request, for the
 * people and projects the tool descriptions name.
 */
export function createServer(app: AppStore, appDir: string, current: TasksStore | null): McpServer {
  const server = new McpServer({ name: "Tasks MCP App", version: "0.1.0" });
  installEvents(server, { app, types: EVENT_TYPES, ProtocolError });
  if (!current) {
    registerSetup(server, app);
    return server;
  }
  const { data } = current;
  const read = <T>(fn: (store: TasksStore) => T) => app.read((db) => fn(TasksStore.load(db)));
  const write = <T>(fn: (store: TasksStore) => T) =>
    app.transact((db) => {
      const store = TasksStore.load(db);
      const result = fn(store);
      store.save(db);
      return result;
    });
  const projectKeys = data.projects.map((p) => `${p.key} (${p.name})`).join(", ");
  const handles = data.people.map((p) => `${p.handle}${p.kind === "agent" ? " (agent)" : ""}`).join(", ");
  const viewer = data.people.find((p) => p.id === data.viewerId)!;

  const projectArg = z.string().describe(`Project key: ${projectKeys}`);
  const personArg = (role: string) =>
    z.string().describe(`${role}: a person id, handle or name (${handles}); "me" is ${viewer.name}`);
  const actorArg = personArg(`Who makes the change, recorded in the activity log; defaults to ${viewer.name}`).optional();
  const keyArg = z.string().describe('Issue key, e.g. "WEB-12"');
  const assigneeFilter = z
    .string()
    .optional()
    .describe(`Only issues assigned to this person (id, handle or name: ${handles}; "me" is ${viewer.name}), or "unassigned"`);
  const dueArg = z.string().describe("Due date, YYYY-MM-DD");
  const labelsArg = z.array(z.string()).describe("Label names; unknown ones are created");
  const estimateArg = z.number().min(0).describe("Estimate in points");

  const detailResult = (store: TasksStore, ref: string, lead?: string) => {
    const detail = buildDetail(store, ref);
    const text = summarizeDetail(detail);
    return { content: [{ type: "text" as const, text: lead ? `${lead}\n\n${text}` : text }], structuredContent: detail };
  };

  registerAppTool(
    server,
    "show_task_board",
    {
      title: "Show task board",
      description:
        "Open the issue board: one column per status (backlog, todo, in progress, in review, done, canceled) with every " +
        "issue's key, title, priority, labels, assignee and due date. Optionally scope it to one project or one assignee.",
      inputSchema: z.object({
        project: projectArg.optional().describe(`Project key to show: ${projectKeys}. Omit for all projects.`),
        assignee: assigneeFilter,
      }),
      outputSchema: boardSnapshotSchema,
      annotations: { readOnlyHint: true },
      _meta: { ui: { resourceUri: BOARD_URI } },
    },
    async ({ project, assignee }) =>
      read((store) => {
        const snapshot = buildSnapshot(store, { project, assignee });
        return { content: [{ type: "text" as const, text: summarizeSnapshot(snapshot) }], structuredContent: snapshot };
      }),
  );

  // Callable by the board only: switching project or assignee in the UI reloads
  // without a model turn in between.
  registerAppTool(
    server,
    "get_board_snapshot",
    {
      title: "Get board snapshot",
      description: "Board data for one project and assignee filter.",
      inputSchema: z.object({
        project: projectArg.optional(),
        assignee: assigneeFilter,
      }),
      outputSchema: boardSnapshotSchema,
      annotations: { readOnlyHint: true },
      _meta: { ui: { resourceUri: BOARD_URI, visibility: ["app"] } },
    },
    async ({ project, assignee }) =>
      read((store) => {
        const snapshot = buildSnapshot(store, { project, assignee });
        return { content: [{ type: "text" as const, text: summarizeSnapshot(snapshot) }], structuredContent: snapshot };
      }),
  );

  registerAppTool(
    server,
    "show_task",
    {
      title: "Show task",
      description:
        "Open one issue: status, priority, assignee, due date, labels, description, sub-issues, comments and the full " +
        "activity log of who changed what.",
      inputSchema: z.object({ key: keyArg }),
      outputSchema: taskDetailSchema,
      annotations: { readOnlyHint: true },
      _meta: { ui: { resourceUri: ISSUE_URI } },
    },
    async ({ key }) => read((store) => detailResult(store, key)),
  );

  server.registerTool(
    "list_tasks",
    {
      title: "List tasks",
      description:
        "Find issues. Every filter is optional and they combine with AND. Rows come in board order: by status, then " +
        `priority, then most recently updated. At most ${LIST_LIMIT} rows unless \`limit\` says otherwise.`,
      inputSchema: z.object({
        project: projectArg.optional(),
        status: z.array(statusSchema).optional().describe("Only issues in one of these statuses"),
        assignee: assigneeFilter,
        label: z.string().optional().describe("Only issues carrying this label"),
        priority: z.array(prioritySchema).optional().describe("Only issues with one of these priorities"),
        overdue: z.boolean().optional().describe("true: only open issues past their due date; false: only the rest"),
        query: z.string().optional().describe("Text to find in the key, title or description"),
        limit: z.number().int().min(1).max(200).optional().describe(`Maximum rows to return, default ${LIST_LIMIT}`),
      }),
      outputSchema: taskListSchema,
      annotations: { readOnlyHint: true },
    },
    async ({ limit, ...filter }) =>
      read((store) => {
        const list = listTasks(store, filter, limit ?? LIST_LIMIT);
        return { content: [{ type: "text" as const, text: summarizeList(list) }], structuredContent: list };
      }),
  );

  server.registerTool(
    "create_task",
    {
      title: "Create task",
      description: "Create an issue in a project. It gets the project's next key (e.g. WEB-61) and starts in Todo unless `status` says otherwise.",
      inputSchema: z.object({
        project: projectArg,
        title: z.string().min(1).describe("One-line summary"),
        description: z.string().optional().describe("Markdown body"),
        status: statusSchema.optional().describe("Starting status, default todo"),
        priority: prioritySchema.optional().describe("Default none"),
        assignee: personArg("Assignee").optional(),
        labels: labelsArg.optional(),
        due: dueArg.optional(),
        estimate: estimateArg.optional(),
        parent: keyArg.optional().describe("Key of the parent issue, making this a sub-issue (same project)"),
        actor: actorArg,
      }),
      outputSchema: taskDetailSchema,
      annotations: { readOnlyHint: false, idempotentHint: false },
    },
    async ({ project, actor, ...fields }) =>
      write((store) => {
        const issue = store.create(project, fields, actor);
        return detailResult(store, issue.key, `Created ${issue.key}.`);
      }),
  );

  server.registerTool(
    "update_task",
    {
      title: "Update task",
      description:
        "Change any field of an issue. Pass only the fields to change; null clears assignee, due, estimate or parent. " +
        "`labels` replaces the whole set. Each real change is recorded in the activity log under `actor`; repeating " +
        "the same update changes nothing.",
      inputSchema: z.object({
        key: keyArg,
        title: z.string().min(1).optional(),
        description: z.string().optional().describe("New markdown body"),
        status: statusSchema.optional(),
        priority: prioritySchema.optional(),
        assignee: personArg("New assignee").nullable().optional(),
        labels: labelsArg.optional(),
        due: dueArg.nullable().optional(),
        estimate: estimateArg.nullable().optional(),
        parent: keyArg.nullable().optional().describe("Key of the new parent issue, or null to detach"),
        actor: actorArg,
      }),
      outputSchema: taskDetailSchema,
      annotations: { readOnlyHint: false, idempotentHint: true },
    },
    async ({ key, actor, ...fields }) =>
      write((store) => {
        const { issue, changed } = store.update(key, fields, actor);
        if (!changed.length) return detailResult(store, issue.key, `${issue.key} already had these values; nothing changed.`);
        const detail = buildDetail(store, issue.key);
        const changes = detail.activity
          .slice(-changed.length)
          .map((a) => (a.kind === "description" ? "description edited" : `${a.kind} ${show(a.kind, a.from)} → ${show(a.kind, a.to)}`));
        return {
          content: [{ type: "text" as const, text: `Updated ${issue.key}: ${changes.join("; ")}.\n\n${summarizeDetail(detail)}` }],
          structuredContent: detail,
        };
      }),
  );

  server.registerTool(
    "add_comment",
    {
      title: "Add comment",
      description: "Add a markdown comment to an issue.",
      inputSchema: z.object({
        key: keyArg,
        body: z.string().min(1).describe("Comment text, markdown"),
        author: personArg(`Comment author; defaults to ${viewer.name}`).optional(),
      }),
      outputSchema: addedCommentSchema,
      annotations: { readOnlyHint: false, idempotentHint: false },
    },
    async ({ key, body, author }) =>
      write((store) => {
        const { issue, comment } = store.comment(key, body, author);
        const person = store.data.people.find((p) => p.id === comment.authorId)!;
        const result: AddedComment = {
          key: issue.key,
          comment: {
            id: comment.id,
            author: { id: person.id, name: person.name, handle: person.handle, kind: person.kind },
            body: comment.body,
            createdAt: comment.createdAt,
          },
          comments: issue.comments.length,
        };
        return {
          content: [
            { type: "text" as const, text: `${person.name} commented on ${issue.key} (${plural(issue.comments.length, "comment")} now).` },
          ],
          structuredContent: result,
        };
      }),
  );

  server.registerTool(
    "add_person",
    {
      title: "Add person",
      description: "Add a teammate, human or agent, who can then be an assignee, project lead or comment author.",
      inputSchema: personFields,
      annotations: { readOnlyHint: false, idempotentHint: false },
    },
    async (fields) =>
      write((store) => {
        const person = store.addPerson(fields);
        return { content: [{ type: "text" as const, text: `Added ${person.name} as @${person.handle} (${person.kind}).` }] };
      }),
  );

  server.registerTool(
    "create_project",
    {
      title: "Create project",
      description: "Create a project. Its issues get keys from the project key: OPS-1, OPS-2 and so on.",
      inputSchema: projectFields(personArg("Project lead")),
      annotations: { readOnlyHint: false, idempotentHint: false },
    },
    async (fields) =>
      write((store) => {
        const project = store.createProject(fields);
        return { content: [{ type: "text" as const, text: `Created project ${project.key} (${project.name}).` }] };
      }),
  );

  for (const view of VIEWS) {
    registerAppResource(
      server,
      view.name,
      view.uri,
      { mimeType: RESOURCE_MIME_TYPE, description: view.description },
      async (): Promise<ReadResourceResult> => ({
        contents: [
          {
            uri: view.uri,
            mimeType: RESOURCE_MIME_TYPE,
            text: await fs.readFile(path.join(appDir, view.file), "utf-8"),
          },
        ],
      }),
    );
  }

  return server;
}

const personFields = z.object({
  name: z.string().min(1).describe("Full name"),
  handle: z.string().min(1).describe('Short unique handle, e.g. "maya"; tools accept it in place of the name'),
  kind: z.enum(PERSON_KINDS).optional().describe("human or agent, default human"),
  title: z.string().optional().describe("Role, e.g. Head of Sales"),
});

const projectFields = (lead: z.ZodString) =>
  z.object({
    key: z.string().min(1).describe('Issue key prefix, 2-10 latin letters and digits, e.g. "OPS"'),
    name: z.string().min(1),
    description: z.string().optional(),
    lead,
  });

/** An instance whose storage holds no tracker yet offers one tool: the one that writes it. */
function registerSetup(server: McpServer, app: AppStore): void {
  server.registerTool(
    "setup_tracker",
    {
      title: "Set up tracker",
      description:
        "This tracker is empty. Write its team, whose tracker it is (the default actor), and its first projects; " +
        "the other tools appear once it is set up. People and projects can be added later.",
      inputSchema: z.object({
        people: z.array(personFields).min(1),
        viewer: z.string().describe("Handle of the person whose tracker this is; \"me\" in later calls"),
        projects: z.array(projectFields(z.string().describe("Handle of the project lead"))).min(1),
      }),
      annotations: { readOnlyHint: false, idempotentHint: false },
    },
    async (setup) => {
      const store = await app.transact((db) => TasksStore.setup(db, setup));
      const { people, projects } = store.data;
      return {
        content: [
          {
            type: "text" as const,
            text:
              `Set up the tracker with ${people.length === 1 ? "1 person" : `${people.length} people`} and ` +
              `${plural(projects.length, "project")}: ${projects.map((p) => p.key).join(", ")}. ` +
              "Reconnect to see the task tools.",
          },
        ],
      };
    },
  );
}
