/**
 * Pure incremental reducer over the canonical event contract.
 *
 * Applying events one-by-one through `applyEvent` yields the same ordered parts
 * as `reduceParts` over the whole list (the supersede invariant). Lifecycle and
 * terminal task.* events are append-only in `timeline`; the last terminal event
 * exposes a user-facing `message` and `status`.
 */

import {
  canonicalType,
  derivePart,
  Part,
  EventData,
  EventInput,
  TERMINAL_TYPES,
  TASK_COMPLETED,
  TASK_FAILED,
  A2UI_DELETE,
} from "./contract";
import { applyA2UI, A2UISurfaceState } from "./a2ui";

export interface TimelineItem {
  eventType: string;
  data: EventData;
}

export type TaskStatus = "running" | "completed" | "failed" | "cancelled";

export interface EventState {
  /** Ordered parts, superseded by partId. */
  parts: Part[];
  /** Insertion index of each partId, so supersede keeps the original slot. */
  order: string[];
  /** Fast lookup for the current part at a partId. */
  byId: Record<string, Part>;
  /** Append-only lifecycle/terminal task.* events, in arrival order. */
  timeline: TimelineItem[];
  /** Terminal status once a task.* terminal event lands, else "running". */
  status: TaskStatus;
  /** User-facing message from the last terminal event, else null. */
  terminalMessage: string | null;
}

export function initialState(): EventState {
  return {
    parts: [],
    order: [],
    byId: {},
    timeline: [],
    status: "running",
    terminalMessage: null,
  };
}

function statusForTerminal(canonical: string): TaskStatus {
  if (canonical === TASK_COMPLETED) return "completed";
  if (canonical === TASK_FAILED) return "failed";
  return "cancelled";
}

function asStr(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value);
  return text || null;
}

function terminalMessageFrom(canonical: string, data: EventData): string {
  const explicit = asStr(data.message);
  if (explicit) return explicit;
  if (canonical === TASK_COMPLETED) {
    return asStr(data.final_response ?? data.result) ?? "Task completed.";
  }
  const reason = asStr(
    data.reason ?? data.error ?? data.blocked_reason ?? data.error_type
  );
  if (canonical === TASK_FAILED) return reason ?? "Task failed.";
  return reason ?? "Task cancelled.";
}

/**
 * Apply one event, returning a new state. Part events supersede by partId in
 * place; terminal events set status/terminalMessage; every lifecycle/terminal
 * event is appended to the timeline.
 */
/** Build the part's data for an a2ui event, accumulating the surface state. */
function a2uiPartData(
  prev: Part | undefined,
  canonical: string,
  surfaceId: string,
  data: EventData
): EventData {
  const prevSurface =
    prev && prev.kind === "a2ui"
      ? (prev.data.surface as A2UISurfaceState | undefined) ?? null
      : null;
  const surface = applyA2UI(prevSurface, canonical, surfaceId, data);
  return { ...data, surface };
}

export function applyEvent(state: EventState, event: EventInput): EventState {
  const canonical = canonicalType(event.eventType);
  const part = derivePart(event.eventType, event.data);

  if (part !== null) {
    // A2UI delete tombstones the surface: remove the part entirely.
    if (canonical === A2UI_DELETE) {
      if (!state.order.includes(part.partId)) return state;
      const byId = { ...state.byId };
      delete byId[part.partId];
      const order = state.order.filter((pid) => pid !== part.partId);
      const parts = order.map((pid) => byId[pid]);
      return { ...state, byId, order, parts };
    }

    // A2UI create/update accumulate the surface across events rather than
    // replacing the payload wholesale like other parts.
    const stored =
      part.kind === "a2ui"
        ? {
            ...part,
            data: a2uiPartData(
              state.byId[part.partId],
              canonical,
              part.partId,
              event.data
            ),
          }
        : part;

    const byId = { ...state.byId, [part.partId]: stored };
    const order = state.order.includes(part.partId)
      ? state.order
      : [...state.order, part.partId];
    const parts = order.map((pid) => byId[pid]);
    return { ...state, byId, order, parts };
  }

  const timeline = [...state.timeline, { eventType: canonical, data: event.data }];
  if (TERMINAL_TYPES.has(canonical)) {
    return {
      ...state,
      timeline,
      status: statusForTerminal(canonical),
      terminalMessage: terminalMessageFrom(canonical, event.data),
    };
  }
  return { ...state, timeline };
}

/** Fold a whole event list from a fresh state (batch equivalent of applyEvent). */
export function reduceState(events: Iterable<EventInput>): EventState {
  let state = initialState();
  for (const event of events) {
    state = applyEvent(state, event);
  }
  return state;
}
