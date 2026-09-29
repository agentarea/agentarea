/**
 * Pure incremental reducer over the canonical event contract.
 *
 * Task status describes the business outcome; executionStatus describes whether
 * the event-producing workflow is working, waiting for a signal, or finished.
 * Applying events one-by-one through `applyEvent` yields the same ordered parts
 * as `reduceParts` over the whole list (the supersede invariant). Lifecycle and
 * terminal task.* events are append-only in `timeline`; the last terminal event
 * exposes a user-facing `message` and `status`.
 */

import { A2UISurfaceState, applyA2UI } from "./a2ui";
import {
  A2UI_DELETE,
  canonicalType,
  derivePart,
  EventData,
  EventInput,
  Part,
  TASK_AWAITING_CONTINUATION,
  TASK_COMPLETED,
  TASK_CONTINUED,
  TASK_FAILED,
  TERMINAL_TYPES,
} from "./contract";

const RUN_BOUNDARY_TYPES = new Set(["task.started", TASK_CONTINUED]);
const FOLLOW_UP_WAIT = "task.awaiting_follow_up";

export interface TimelineItem {
  eventType: string;
  data: EventData;
}

export interface CompletedRun {
  id: string;
  partIds: string[];
  terminalType: string;
  terminalMessage: string | null;
  terminalAnswer: string | null;
}

export type TaskStatus =
  | "running"
  | "waiting_for_input"
  | "waiting_for_approval"
  | "blocked"
  | "waiting_for_continuation"
  | "completed"
  | "failed"
  | "cancelled";

export interface EventState {
  /** Ordered parts, superseded by partId. */
  parts: Part[];
  /** Insertion index of each partId, so supersede keeps the original slot. */
  order: string[];
  /** Fast lookup for the current part at a partId. */
  byId: Record<string, Part>;
  /** Append-only lifecycle/terminal task.* events, in arrival order. */
  timeline: TimelineItem[];
  /** Business state, independent of a live workflow's follow-up wait. */
  status: TaskStatus;
  executionStatus: "running" | "waiting" | "finished";
  /** User-facing message from the last terminal event, else null. */
  terminalMessage: string | null;
  /** Snapshots of work completed by authoritative task.* terminal events. */
  completedRuns: CompletedRun[];
}

export function initialState(): EventState {
  return {
    parts: [],
    order: [],
    byId: {},
    timeline: [],
    status: "running",
    executionStatus: "running",
    terminalMessage: null,
    completedRuns: [],
  };
}

function statusForTerminal(canonical: string, data: EventData): TaskStatus {
  if (canonical === TASK_COMPLETED || canonical === FOLLOW_UP_WAIT)
    return "completed";
  if (canonical === TASK_FAILED)
    return data.blocked === true || data.status === "blocked"
      ? "blocked"
      : "failed";
  return "cancelled";
}

function asStr(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value);
  return text || null;
}

/**
 * The user-facing line for a terminal event, in the order the backend contract
 * (agentarea_common/events/contract.py) fills `message`. The banner and the
 * timeline row both read it, so they can never disagree.
 */
export function terminalMessage(canonical: string, data: EventData): string {
  const explicit = asStr(data.message);
  if (explicit) return explicit;
  if (canonical === TASK_COMPLETED || canonical === FOLLOW_UP_WAIT) {
    return asStr(data.final_response ?? data.result) ?? "Task completed.";
  }
  const reason = asStr(
    data.reason ?? data.error ?? data.blocked_reason ?? data.error_type
  );
  if (canonical === TASK_FAILED) return reason ?? "Task failed.";
  return reason ?? "Task cancelled.";
}

/** Only requests belonging to the current, live turn can accept a response. */
export function findPendingForm(state: EventState): Part | null {
  if (state.executionStatus === "finished") return null;
  return (
    state.parts.find(
      (part) =>
        (part.eventType === "input.request" ||
          part.eventType === "approval.request") &&
        part.data.interactionClosed !== true &&
        !state.completedRuns.some((run) => run.partIds.includes(part.partId))
    ) ?? null
  );
}

/** Disable historical controls without changing their recorded event payload. */
export function isInteractionClosed(state: EventState, part: Part): boolean {
  if (
    state.executionStatus === "finished" ||
    part.data.interactionClosed === true
  )
    return true;
  if (part.kind === "form") {
    return state.completedRuns.some((run) => run.partIds.includes(part.partId));
  }
  return false;
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
      ? ((prev.data.surface as A2UISurfaceState | undefined) ?? null)
      : null;
  const surface = applyA2UI(prevSurface, canonical, surfaceId, data);
  return {
    ...data,
    surface,
    interactionClosed:
      canonical !== "a2ui.create" && prev?.data.interactionClosed === true,
  };
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
    if (
      canonical === "input.response" &&
      typeof event.data.surface_id === "string"
    ) {
      const surface = byId[event.data.surface_id];
      if (surface?.kind === "a2ui") {
        byId[surface.partId] = {
          ...surface,
          data: { ...surface.data, interactionClosed: true },
        };
      }
    }
    const order = state.order.includes(part.partId)
      ? state.order
      : [...state.order, part.partId];
    const parts = order.map((pid) => byId[pid]);
    const next = { ...state, byId, order, parts };
    if (
      canonical === "llm.call.started" &&
      state.status === "completed" &&
      state.executionStatus === "waiting"
    ) {
      return {
        ...next,
        status: "running",
        executionStatus: "running",
        terminalMessage: null,
      };
    }
    if (part.kind === "form" && state.executionStatus !== "finished") {
      const pending = findPendingForm(next);
      if (pending) {
        return {
          ...next,
          status:
            pending.eventType === "approval.request"
              ? "waiting_for_approval"
              : "waiting_for_input",
          executionStatus: "waiting",
          terminalMessage: null,
        };
      }
      if (
        state.status === "waiting_for_input" ||
        state.status === "waiting_for_approval"
      ) {
        return { ...next, status: "running", executionStatus: "running" };
      }
    }
    return next;
  }

  const timeline = [
    ...state.timeline,
    { eventType: canonical, data: event.data },
  ];
  if (TERMINAL_TYPES.has(canonical) || canonical === FOLLOW_UP_WAIT) {
    const completedIds = new Set(
      state.completedRuns.flatMap((run) => run.partIds)
    );
    const runParts = state.parts.filter(
      (part) => !completedIds.has(part.partId)
    );
    const hasNewParts = runParts.length > 0;
    let lastTerminalIndex = -1;
    for (let index = state.timeline.length - 1; index >= 0; index -= 1) {
      if (
        TERMINAL_TYPES.has(state.timeline[index].eventType) ||
        state.timeline[index].eventType === FOLLOW_UP_WAIT
      ) {
        lastTerminalIndex = index;
        break;
      }
    }
    const hasNewRunBoundary = state.timeline
      .slice(lastTerminalIndex + 1)
      .some((item) => RUN_BOUNDARY_TYPES.has(item.eventType));
    const completedRun: CompletedRun = {
      id: `run-${state.completedRuns.length + 1}`,
      partIds: runParts.map((part) => part.partId),
      terminalType: canonical,
      terminalMessage: terminalMessage(canonical, event.data),
      terminalAnswer:
        typeof event.data.final_response === "string"
          ? event.data.final_response
          : typeof event.data.result === "string"
            ? event.data.result
            : null,
    };
    const lastRun = state.completedRuns[state.completedRuns.length - 1];
    // A failure reported after the run already closed, with nothing run in
    // between, is how that same run ended — not a run of its own.
    const endsLastRun =
      !hasNewParts &&
      !hasNewRunBoundary &&
      lastRun !== undefined &&
      canonical !== TASK_COMPLETED &&
      canonical !== FOLLOW_UP_WAIT &&
      state.timeline[lastTerminalIndex]?.eventType !== FOLLOW_UP_WAIT;
    return {
      ...state,
      timeline,
      status: statusForTerminal(canonical, event.data),
      executionStatus:
        canonical === FOLLOW_UP_WAIT ||
        event.data.execution_status === "waiting"
          ? "waiting"
          : "finished",
      terminalMessage: completedRun.terminalMessage,
      completedRuns: endsLastRun
        ? [
            ...state.completedRuns.slice(0, -1),
            {
              ...lastRun,
              terminalType: canonical,
              terminalMessage: completedRun.terminalMessage,
            },
          ]
        : hasNewParts ||
            (Boolean(completedRun.terminalAnswer) &&
              (state.completedRuns.length === 0 || hasNewRunBoundary))
          ? [...state.completedRuns, completedRun]
          : state.completedRuns,
    };
  }
  if (canonical === "execution.finished") {
    return { ...state, timeline, executionStatus: "finished" };
  }
  if (canonical === TASK_AWAITING_CONTINUATION) {
    return {
      ...state,
      timeline,
      status: "waiting_for_continuation",
      executionStatus: "waiting",
    };
  }
  if (RUN_BOUNDARY_TYPES.has(canonical)) {
    const byId = { ...state.byId };
    if (canonical === "task.started") {
      for (const part of state.parts) {
        if (part.kind === "form" || part.kind === "a2ui") {
          byId[part.partId] = {
            ...part,
            data: { ...part.data, interactionClosed: true },
          };
        }
      }
    }
    return {
      ...state,
      byId,
      parts: state.order.map((id) => byId[id]),
      timeline,
      status: "running",
      executionStatus: "running",
      terminalMessage: null,
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
