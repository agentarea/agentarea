/**
 * How one task event reads in the events table: what it is about, its own
 * words, and the few facts in its data worth seeing without opening it.
 */

import {
  isUnavailableToolValue,
  stripUnavailableToolValues,
} from "@/components/Chat/utils/toolDetails";
import { isTaskEventType, type TaskEventType } from "@/lib/events/contract";

export type EventCategory =
  | "task"
  | "turn"
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

/** Category of each scope, the part of the type before its first dot. */
const CATEGORY_BY_SCOPE: Readonly<Record<string, EventCategory>> = {
  task: "task",
  execution: "task",
  command: "task",
  delegation: "task",
  turn: "turn",
  llm: "llm",
  model: "llm",
  answer: "llm",
  tool: "tool",
  input: "input",
  message: "input",
  approval: "approval",
  artifact: "artifact",
  a2ui: "ui",
  budget: "budget",
  service: "budget",
  context: "context",
  runtime: "runtime",
  skill: "runtime",
};

export function eventCategory(type: string): EventCategory {
  return CATEGORY_BY_SCOPE[type.split(".", 1)[0]] ?? "other";
}

/**
 * Catalog key (under `TaskEventsPage.types`) of the name each type of the
 * closed vocabulary (lib/events/contract.ts) reads as.
 */
const TYPE_KEYS: Readonly<Record<TaskEventType, string>> = {
  "task.started": "taskStarted",
  "task.completed": "taskCompleted",
  "task.failed": "taskFailed",
  "task.cancelled": "taskCancelled",
  "task.awaiting_follow_up": "taskAwaitingFollowUp",
  "task.awaiting_continuation": "taskAwaitingContinuation",
  "task.continued": "taskContinued",
  "task.awaiting_infrastructure": "taskAwaitingInfrastructure",
  "task.infrastructure_recovered": "taskInfrastructureRecovered",
  "skill.withheld": "skillWithheld",
  "task.retried": "taskRetried",
  "execution.finished": "executionFinished",
  "execution.continued_as_new": "executionContinuedAsNew",
  "execution.paused": "executionPaused",
  "execution.resumed": "executionResumed",
  "turn.started": "turnStarted",
  "turn.completed": "turnCompleted",
  "turn.aborted": "turnAborted",
  "llm.call.started": "llmCallStarted",
  "llm.call.completed": "llmCallCompleted",
  "llm.call.failed": "llmCallFailed",
  "llm.call.chunk": "llmCallChunk",
  "tool.call": "toolCall",
  "tool.result": "toolResult",
  "tool.progress": "toolProgress",
  "input.request": "inputRequest",
  "input.submitted": "inputSubmitted",
  "input.response": "inputResponse",
  "approval.requested": "approvalRequest",
  "approval.decided": "approvalResponse",
  "message.queued": "messageQueued",
  "message.received": "messageReceived",
  "message.removed": "messageRemoved",
  "command.received": "commandReceived",
  "command.rejected": "commandRejected",
  "budget.warning": "budgetWarning",
  "budget.exceeded": "budgetExceeded",
  "budget.updated": "budgetUpdated",
  "service.payment": "servicePayment",
  "service.budget_warning": "serviceBudgetWarning",
  "service.budget_exceeded": "serviceBudgetExceeded",
  "context.warning": "contextWarning",
  "context.compacted": "contextCompacted",
  "answer.checked": "answerChecked",
  "model.changed": "modelChanged",
  "model.fallback": "modelFallback",
  "model.unavailable": "modelUnavailable",
  "runtime.discovered": "runtimeDiscovered",
  "delegation.started": "delegationStarted",
  "delegation.completed": "delegationCompleted",
  "delegation.failed": "delegationFailed",
  "artifact.validation.started": "artifactValidationStarted",
  "artifact.validation.completed": "artifactValidationCompleted",
  "artifact.created": "artifactCreated",
  "artifact.updated": "artifactUpdated",
  "a2ui.create": "uiCreated",
  "a2ui.update.components": "uiUpdated",
  "a2ui.update.data": "uiUpdated",
  "a2ui.delete": "uiDeleted",
};

export function eventTypeKey(type: string): string | null {
  return isTaskEventType(type) ? TYPE_KEYS[type] : null;
}

/**
 * A dotted type split before its last part: `llm.call.` and `completed`. The
 * scope repeats down the table; what happened is the part to read. A type
 * with no dot is all action.
 */
export function splitEventType(type: string): {
  scope: string;
  action: string;
} {
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
    // A marker standing in for a body the event did not keep is not its words.
    if (
      typeof value === "string" &&
      value.trim() &&
      !isUnavailableToolValue(value.trim())
    )
      return value.trim();
  }
  return null;
}

export type EventFact =
  | { kind: "tool"; value: string }
  | { kind: "arguments"; value: string[] }
  | { kind: "model"; value: string }
  | { kind: "iteration"; value: number }
  | { kind: "messages"; value: number }
  | { kind: "tokens"; input: number; output: number; cached: number | null }
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

/**
 * The model an event names: the one that answered (`model_name`), or for a
 * change, the old and the new one.
 */
function modelOf(data: Record<string, unknown>): string | null {
  const to = text(record(data.to)?.model_name) ?? text(data.new_model);
  if (to) {
    const from = text(record(data.from)?.model_name) ?? text(data.old_model);
    return from ? `${from} → ${to}` : to;
  }
  return text(data.model) ?? text(data.model_name);
}

/** The facts an event's data carries, in the order they read best. */
export function eventFacts(
  data: Record<string, unknown> | undefined
): EventFact[] {
  if (!data) return [];
  const facts: EventFact[] = [];

  const tool =
    text(data.tool_name) ?? text(data.skill_name) ?? text(data.script_name);
  if (tool) facts.push({ kind: "tool", value: tool });

  const args = record(data.arguments);
  if (args && Object.keys(args).length > 0) {
    facts.push({ kind: "arguments", value: Object.keys(args) });
  }

  const model = modelOf(data);
  if (model) facts.push({ kind: "model", value: model });

  const iteration = count(data.iteration);
  if (iteration !== null) facts.push({ kind: "iteration", value: iteration });

  const messages = count(data.message_count);
  if (messages !== null) facts.push({ kind: "messages", value: messages });

  // llm.call.completed nests the counts: data.usage = { cost, usage: {...} }.
  const outerUsage = record(data.usage);
  const usage = record(outerUsage?.usage) ?? outerUsage;
  if (usage) {
    const input = count(usage.prompt_tokens ?? usage.input_tokens);
    const output = count(usage.completion_tokens ?? usage.output_tokens);
    const cached = count(usage.cached_prompt_tokens);
    if (input !== null && output !== null) {
      facts.push({ kind: "tokens", input, output, cached: cached || null });
    }
  }

  const cost = count(data.cost ?? data.total_cost);
  if (cost !== null) facts.push({ kind: "cost", value: cost });

  const errorType = text(data.error_type);
  if (errorType) facts.push({ kind: "errorType", value: errorType });

  return facts;
}

/**
 * The event's data as the details show it: markers standing in for values the
 * log did not keep are left out, and null when nothing else is there.
 */
export function shownEventData(
  data: Record<string, unknown> | undefined
): Record<string, unknown> | null {
  const kept = record(stripUnavailableToolValues(data));
  return kept && Object.keys(kept).length > 0 ? kept : null;
}
