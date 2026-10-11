/**
 * How one task event reads in the events table: what it is about, its own
 * words, and the few facts in its data worth seeing without opening it.
 */

export type EventCategory =
  | "task"
  | "iteration"
  | "llm"
  | "tool"
  | "input"
  | "approval"
  | "artifact"
  | "ui"
  | "budget"
  | "context"
  | "runtime"
  | "other";

/** Checked in order against the lower-cased type; the first match wins. */
const CATEGORY_PREFIXES: readonly [string, EventCategory][] = [
  ["llm.", "llm"],
  ["tool.", "tool"],
  ["input.", "input"],
  ["approval.", "approval"],
  ["humanapproval", "approval"],
  ["artifact.", "artifact"],
  ["a2ui.", "ui"],
  ["task.", "task"],
  ["execution.", "task"],
  ["workflow", "task"],
  ["iteration", "iteration"],
  ["budget", "budget"],
  ["context", "context"],
  ["runtime", "runtime"],
];

export function eventCategory(type: string): EventCategory {
  const lower = type.toLowerCase();
  return (
    CATEGORY_PREFIXES.find(([prefix]) => lower.startsWith(prefix))?.[1] ??
    "other"
  );
}

/**
 * Catalog key (under `TaskEventsPage.types`) of the name a known type reads
 * as. The backend vocabulary is fixed (agentarea_common/events/contract.py
 * plus the workflow's own CamelCase events); a type missing here keeps its
 * raw name.
 */
const TYPE_KEYS: Readonly<Record<string, string>> = {
  "task.started": "taskStarted",
  "task.completed": "taskCompleted",
  "task.failed": "taskFailed",
  "task.cancelled": "taskCancelled",
  "task.awaiting_follow_up": "taskAwaitingFollowUp",
  "task.awaiting_continuation": "taskAwaitingContinuation",
  "task.continued": "taskContinued",
  "execution.finished": "executionFinished",
  "llm.call.started": "llmCallStarted",
  "llm.call.completed": "llmCallCompleted",
  "llm.call.failed": "llmCallFailed",
  "llm.call.chunk": "llmCallChunk",
  "tool.call": "toolCall",
  "tool.result": "toolResult",
  "input.request": "inputRequest",
  "input.response": "inputResponse",
  "approval.request": "approvalRequest",
  "approval.response": "approvalResponse",
  HumanApprovalRequested: "approvalRequest",
  "artifact.created": "artifactCreated",
  "artifact.updated": "artifactUpdated",
  "a2ui.create": "uiCreated",
  "a2ui.update.components": "uiUpdated",
  "a2ui.update.data": "uiUpdated",
  "a2ui.delete": "uiDeleted",
  IterationStarted: "iterationStarted",
  IterationCompleted: "iterationCompleted",
  BudgetWarning: "budgetWarning",
  BudgetExceeded: "budgetExceeded",
  ContextCompacted: "contextCompacted",
  ContextWindowExceeded: "contextWindowExceeded",
  RuntimeDiscovered: "runtimeDiscovered",
  RuntimeError: "runtimeError",
  WorkflowStarted: "workflowStarted",
  WorkflowCompleted: "workflowCompleted",
  WorkflowFailed: "workflowFailed",
  WorkflowCancelled: "workflowCancelled",
  WorkflowContinuedAsNew: "workflowContinuedAsNew",
  WorkflowCommandReceived: "commandReceived",
  WorkflowCommandRejected: "commandRejected",
};

export function eventTypeKey(type: string): string | null {
  return TYPE_KEYS[type] ?? null;
}

/**
 * A dotted type split before its last part: `llm.call.` and `completed`. The
 * scope repeats down the table; what happened is the part to read. A type
 * with no dot is all action.
 */
export function splitEventType(type: string): { scope: string; action: string } {
  const dot = type.lastIndexOf(".");
  return dot === -1
    ? { scope: "", action: type }
    : { scope: type.slice(0, dot + 1), action: type.slice(dot + 1) };
}

/** Where an event keeps its own words, most telling first. */
const SUMMARY_KEYS = [
  "message",
  "content",
  "result",
  "error",
  "reason",
  "goal_description",
  "question",
] as const;

/** The event's own words: its message, the model's reply, a result or error. */
export function eventSummary(
  data: Record<string, unknown> | undefined
): string | null {
  for (const key of SUMMARY_KEYS) {
    const value = data?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

export type EventFact =
  | { kind: "tool"; value: string }
  | { kind: "arguments"; value: string[] }
  | { kind: "model"; value: string }
  | { kind: "iteration"; value: number }
  | { kind: "messages"; value: number }
  | { kind: "tokens"; input: number; output: number }
  | { kind: "cost"; value: number }
  | { kind: "errorType"; value: string };

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function count(value: unknown): number | null {
  const n = typeof value === "string" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** The facts an event's data carries, in the order they read best. */
export function eventFacts(
  data: Record<string, unknown> | undefined
): EventFact[] {
  if (!data) return [];
  const facts: EventFact[] = [];

  const tool = text(data.tool_name) ?? text(data.skill_name) ?? text(data.script_name);
  if (tool) facts.push({ kind: "tool", value: tool });

  const args = record(data.arguments);
  if (args && Object.keys(args).length > 0) {
    facts.push({ kind: "arguments", value: Object.keys(args) });
  }

  const model = text(data.model);
  if (model) facts.push({ kind: "model", value: model });

  const iteration = count(data.iteration);
  if (iteration !== null) facts.push({ kind: "iteration", value: iteration });

  const messages = count(data.message_count);
  if (messages !== null) facts.push({ kind: "messages", value: messages });

  const usage = record(data.usage);
  if (usage) {
    const input = count(usage.prompt_tokens ?? usage.input_tokens);
    const output = count(usage.completion_tokens ?? usage.output_tokens);
    if (input !== null && output !== null) {
      facts.push({ kind: "tokens", input, output });
    }
  }

  const cost = count(data.cost ?? data.total_cost);
  if (cost !== null) facts.push({ kind: "cost", value: cost });

  const errorType = text(data.error_type);
  if (errorType) facts.push({ kind: "errorType", value: errorType });

  return facts;
}
