/**
 * Canonical event contract: dotted taxonomy and supersede-by-id parts.
 *
 * Pure, side-effect-free mirror of the backend contract
 * (agentarea_common/events/contract.py). The source emits the canonical dotted
 * names directly — there is no second vocabulary and no alias-on-read bridge.
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
export const APPROVAL_REQUEST = "approval.request";
export const APPROVAL_RESPONSE = "approval.response";
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

export type PartKind = "llm" | "tool" | "form" | "artifact" | "a2ui";

const KIND_BY_TYPE: Record<string, PartKind> = {
  [LLM_STARTED]: "llm",
  [LLM_COMPLETED]: "llm",
  [LLM_FAILED]: "llm",
  [LLM_CHUNK]: "llm",
  [TOOL_CALL]: "tool",
  [TOOL_RESULT]: "tool",
  [INPUT_REQUEST]: "form",
  [INPUT_RESPONSE]: "form",
  [APPROVAL_REQUEST]: "form",
  [APPROVAL_RESPONSE]: "form",
  [ARTIFACT_CREATED]: "artifact",
  [ARTIFACT_UPDATED]: "artifact",
  [A2UI_CREATE]: "a2ui",
  [A2UI_UPDATE_COMPONENTS]: "a2ui",
  [A2UI_UPDATE_DATA]: "a2ui",
  [A2UI_DELETE]: "a2ui",
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
    if (canonical === APPROVAL_REQUEST || canonical === APPROVAL_RESPONSE) {
      return asStr(data.escalation_id ?? data.request_id);
    }
    return asStr(data.input_request_id ?? data.request_id);
  }
  if (kind === "a2ui") {
    return asStr(data.surface_id);
  }
  return asStr(data.artifact_id);
}

/** Derive the superseding Part for an event, or null for lifecycle events. */
export function derivePart(eventType: string, data: EventData): Part | null {
  const canonical = canonicalType(eventType);
  const kind = KIND_BY_TYPE[canonical];
  if (!kind) return null;
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
