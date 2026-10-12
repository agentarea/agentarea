import { z } from "zod";
import { ACTIVITY_KINDS, LABEL_COLORS, PERSON_KINDS, PRIORITIES, STATUSES } from "./tasks.ts";

export const statusSchema = z.enum(STATUSES);
export const prioritySchema = z.enum(PRIORITIES);

export const personRefSchema = z.object({
  id: z.string(),
  name: z.string(),
  handle: z.string(),
  kind: z.enum(PERSON_KINDS),
});

export const personSchema = personRefSchema.extend({ title: z.string() });

export const labelSchema = z.object({ name: z.string(), color: z.enum(LABEL_COLORS) });

/** One issue as a compact row: what the board, the list and `list_tasks` show. */
export const taskRowSchema = z.object({
  id: z.string(),
  key: z.string(),
  project: z.string().describe("Project key"),
  title: z.string(),
  status: statusSchema,
  priority: prioritySchema,
  assignee: personRefSchema.nullable(),
  labels: z.array(z.string()),
  dueDate: z.string().nullable(),
  overdue: z.boolean(),
  estimate: z.number().nullable(),
  parentKey: z.string().nullable(),
  subIssues: z.object({ total: z.number(), done: z.number() }),
  comments: z.number(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

const projectSummarySchema = z.object({
  id: z.string(),
  key: z.string(),
  name: z.string(),
  description: z.string(),
  open: z.number().describe("Issues not done or canceled"),
});

/** Everything the board view renders; `show_task_board` and `get_board_snapshot` return it. */
export const boardSnapshotSchema = z.object({
  asOf: z.string(),
  /** The tracker's clock: the dataset's `asOf` until real time passes it. */
  now: z.string(),
  generatedAt: z.string(),
  viewer: personRefSchema,
  project: z.string().nullable().describe("Project key the board is scoped to; null for all projects"),
  assignee: z.string().nullable().describe('Person id the board is filtered to, "unassigned", or null for anyone'),
  projects: z.array(projectSummarySchema),
  people: z.array(personSchema),
  labels: z.array(labelSchema),
  counts: z.record(statusSchema, z.number()),
  tasks: z.array(taskRowSchema),
});

export const commentSchema = z.object({
  id: z.string(),
  author: personRefSchema,
  body: z.string(),
  createdAt: z.string(),
});

/** One change, with `from`/`to` already turned into display text (names, keys, dates). */
export const activityEntrySchema = z.object({
  id: z.string(),
  actor: personRefSchema,
  at: z.string(),
  kind: z.enum(ACTIVITY_KINDS),
  from: z.string().nullable(),
  to: z.string().nullable(),
});

/** One issue in full; `show_task`, `create_task` and `update_task` return it. */
export const taskDetailSchema = taskRowSchema.extend({
  asOf: z.string(),
  now: z.string(),
  generatedAt: z.string(),
  description: z.string(),
  projectName: z.string(),
  creator: personRefSchema,
  parent: z.object({ key: z.string(), title: z.string(), status: statusSchema }).nullable(),
  children: z.array(taskRowSchema),
  commentList: z.array(commentSchema),
  activity: z.array(activityEntrySchema),
  people: z.array(personSchema),
  labelPalette: z.array(labelSchema),
});

export const taskListSchema = z.object({
  total: z.number().describe("Issues matching the filters"),
  returned: z.number(),
  tasks: z.array(taskRowSchema),
});

export const addedCommentSchema = z.object({
  key: z.string(),
  comment: commentSchema,
  comments: z.number().describe("Comments on the issue now"),
});

export type PersonRef = z.infer<typeof personRefSchema>;
export type PersonInfo = z.infer<typeof personSchema>;
export type TaskRow = z.infer<typeof taskRowSchema>;
export type BoardSnapshot = z.infer<typeof boardSnapshotSchema>;
export type CommentEntry = z.infer<typeof commentSchema>;
export type ActivityEntry = z.infer<typeof activityEntrySchema>;
export type TaskDetail = z.infer<typeof taskDetailSchema>;
export type TaskList = z.infer<typeof taskListSchema>;
export type AddedComment = z.infer<typeof addedCommentSchema>;
