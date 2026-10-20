/**
 * Canonical event contract: the closed task-event vocabulary and
 * supersede-by-id parts.
 *
 * Pure, side-effect-free mirror of the backend contract
 * (agentarea_common/events/contract.py). The source emits only the names in
 * EVENT_TYPES — there is no second vocabulary and no alias-on-read bridge.
 *
 * The whole point is supersede-by-id: every non-lifecycle event maps to a Part
 * with a stable partId; a later event with the same partId replaces that part
 * in place. Lifecycle/terminal task.* events derive no Part.
 */

export const LLM_STARTED = "llm.call.started";
export const LLM_COMPLETED = "llm.call.completed";
export const LLM_FAILED = "llm.call.failed";
export const LLM_CHUNK = "llm.call.chunk";
export const TOOL_CALL = "tool.call";
export const TOOL_RESULT = "tool.result";
export const INPUT_REQUEST = "input.request";
export const INPUT_RESPONSE = "input.response";
export const APPROVAL_REQUESTED = "approval.requested";
export const APPROVAL_DECIDED = "approval.decided";
export const ARTIFACT_CREATED = "artifact.created";
export const ARTIFACT_UPDATED = "artifact.updated";
export const A2UI_CREATE = "a2ui.create";
export const A2UI_UPDATE_COMPONENTS = "a2ui.update.components";
export const A2UI_UPDATE_DATA = "a2ui.update.data";
export const A2UI_DELETE = "a2ui.delete";
export const TASK_COMPLETED = "task.completed";
export const TASK_FAILED = "task.failed";
export const TASK_CANCELLED = "task.cancelled";
export const TASK_AWAITING_CONTINUATION = "task.awaiting_continuation";
export const TASK_CONTINUED = "task.continued";
export const TASK_AWAITING_INFRASTRUCTURE = "task.awaiting_infrastructure";
export const TASK_INFRASTRUCTURE_RECOVERED = "task.infrastructure_recovered";
export const MESSAGE_RECEIVED = "message.received";
export const CONTEXT_COMPACTED = "context.compacted";

/** Mirrors VOCABULARY_VERSION in contract.py; bumps with every change to EVENT_TYPES. */
export const VOCABULARY_VERSION = 5;

/**
 * The closed task-event vocabulary, the same list as EVENT_TYPES in
 * contract.py (where each type is described in one line).
 */
export const EVENT_TYPES = [
  "task.started",
  "task.completed",
  "task.failed",
  "task.cancelled",
  "task.awaiting_follow_up",
  "task.awaiting_continuation",
  "task.continued",
  "task.awaiting_infrastructure",
  "task.infrastructure_recovered",
  "task.retried",
  "execution.finished",
  "execution.continued_as_new",
  "execution.paused",
  "execution.resumed",
  "turn.started",
  "turn.completed",
  "turn.aborted",
  "llm.call.started",
  "llm.call.chunk",
  "llm.call.completed",
  "llm.call.failed",
  "tool.call",
  "tool.result",
  "tool.progress",
  "approval.requested",
  "approval.decided",
  "input.request",
  "input.submitted",
  "input.response",
  "message.queued",
  "message.received",
  "message.removed",
  "command.received",
  "command.rejected",
  "budget.warning",
  "budget.exceeded",
  "budget.updated",
  "service.payment",
  "service.budget_warning",
  "service.budget_exceeded",
  "context.warning",
  "context.compacted",
  "answer.checked",
  "model.changed",
  "model.fallback",
  "model.unavailable",
  "runtime.discovered",
  "delegation.started",
  "delegation.completed",
  "delegation.failed",
  "artifact.validation.started",
  "artifact.validation.completed",
  "artifact.created",
  "artifact.updated",
  "a2ui.create",
  "a2ui.update.components",
  "a2ui.update.data",
  "a2ui.delete",
] as const;

export type TaskEventType = (typeof EVENT_TYPES)[number];

const KNOWN_TYPES: ReadonlySet<string> = new Set(EVENT_TYPES);

export function isTaskEventType(type: string): type is TaskEventType {
  return KNOWN_TYPES.has(type);
}

/**
 * Signals that matter only while the run is live: broadcast, never stored, so
 * a reload or the history never has them (LIVE_ONLY_TYPES in contract.py).
 */
export const LIVE_ONLY_TYPES: ReadonlySet<string> = new Set([
  LLM_STARTED,
  LLM_CHUNK,
  "tool.progress",
]);

export const TERMINAL_TYPES: ReadonlySet<string> = new Set([
  TASK_COMPLETED,
  TASK_FAILED,
  TASK_CANCELLED,
]);

/**
 * Return the canonical dotted event type (identity for canonical inputs). The
 * source already emits canonical names, so this only strips a leading
 * `workflow.` prefix defensively.
 */
export function canonicalType(eventType: string): string {
  return eventType.startsWith("workflow.")
    ? eventType.slice("workflow.".length)
    : eventType;
}

/**
 * A notice marks a moment in the run (a context compaction), not output; a
 * message is a person's message entering the conversation.
 */
export type PartKind =
  | "llm"
  | "tool"
  | "form"
  | "artifact"
  | "a2ui"
  | "notice"
  | "message";

const KIND_BY_TYPE: Record<string, PartKind> = {
  [LLM_STARTED]: "llm",
  [LLM_COMPLETED]: "llm",
  [LLM_FAILED]: "llm",
  [LLM_CHUNK]: "llm",
  [TOOL_CALL]: "tool",
  [TOOL_RESULT]: "tool",
  [INPUT_REQUEST]: "form",
  [INPUT_RESPONSE]: "form",
  [APPROVAL_REQUESTED]: "form",
  [APPROVAL_DECIDED]: "form",
  [ARTIFACT_CREATED]: "artifact",
  [ARTIFACT_UPDATED]: "artifact",
  [A2UI_CREATE]: "a2ui",
  [A2UI_UPDATE_COMPONENTS]: "a2ui",
  [A2UI_UPDATE_DATA]: "a2ui",
  [A2UI_DELETE]: "a2ui",
  [CONTEXT_COMPACTED]: "notice",
  [MESSAGE_RECEIVED]: "message",
};

export type EventData = Record<string, unknown>;

export interface Part {
  partId: string;
  kind: PartKind;
  eventType: string;
  data: EventData;
}

function asStr(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value);
  return text || null;
}

function partIdFor(
  kind: PartKind,
  canonical: string,
  data: EventData
): string | null {
  if (kind === "tool") {
    return asStr(data.tool_call_id);
  }
  if (kind === "llm") {
    const executionId = data.execution_id;
    const iteration = data.iteration;
    if (
      executionId === null ||
      executionId === undefined ||
      iteration === null ||
      iteration === undefined
    ) {
      return null;
    }
    return `${executionId}:${iteration}`;
  }
  if (kind === "form") {
    if (canonical === APPROVAL_REQUESTED || canonical === APPROVAL_DECIDED) {
      return asStr(data.escalation_id ?? data.request_id);
    }
    return asStr(data.input_request_id ?? data.request_id);
  }
  if (kind === "a2ui") {
    return asStr(data.surface_id);
  }
  if (kind === "notice" || kind === "message") {
    return asStr(data.event_id);
  }
  return asStr(data.artifact_id);
}

/** Derive the superseding Part for an event, or null for lifecycle events. */
export function derivePart(eventType: string, data: EventData): Part | null {
  const canonical = canonicalType(eventType);
  const kind = KIND_BY_TYPE[canonical];
  if (!kind) return null;
  // A compaction call is billed as llm.call.completed but is not an assistant
  // reply; it must never create or overwrite a transcript part.
  if (kind === "llm" && data.purpose === "compaction") return null;
  const partId = partIdFor(kind, canonical, data);
  if (partId === null) return null;
  return { partId, kind, eventType: canonical, data };
}

export interface EventInput {
  eventType: string;
  data: EventData;
}

/**
 * Fold an event stream into ordered parts via supersede-by-id. Non-part events
 * are skipped. A later part with an existing partId replaces the earlier one at
 * its original position.
 */
export function reduceParts(events: Iterable<EventInput>): Part[] {
  const order: string[] = [];
  const byId = new Map<string, Part>();
  for (const { eventType, data } of events) {
    const part = derivePart(eventType, data);
    if (part === null) continue;
    if (!byId.has(part.partId)) order.push(part.partId);
    byId.set(part.partId, part);
  }
  return order.map((pid) => byId.get(pid) as Part);
}
