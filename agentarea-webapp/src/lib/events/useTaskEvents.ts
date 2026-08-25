import { useCallback, useEffect, useRef, useState } from "react";
import { getTaskEvents } from "@/hooks/actions";
import { apiErrorMessage } from "@/lib/api-errors";
import { useSSE } from "@/hooks/useSSE";
import type {
  DisplayEvent,
  EventLevel,
  WorkflowEventType,
} from "@/types/events";
import { canonicalType, EventInput, Part, TERMINAL_TYPES } from "./contract";
import { normalizeHistory, normalizeSSEEvent } from "./normalize";
import {
  applyEvent,
  EventState,
  initialState,
  TimelineItem,
  TaskStatus,
} from "./reducer";

/**
 * Single SSE hook over the canonical event contract. Loads history for catch-up,
 * subscribes to the live task stream, and folds every event through the
 * reducer. Returns both the reduced view (parts/timeline, supersede-collapsed)
 * and an append-only raw event log for the debug/events inspector.
 */

type RawData = Record<string, unknown>;

function isTerminal(eventType: string): boolean {
  return TERMINAL_TYPES.has(canonicalType(eventType));
}

// SSE transport/control frames (connection lifecycle, keepalives) are not task
// events and must never render or feed the reducer.
const CONTROL_TYPES = new Set([
  "connected",
  "disconnected",
  "ping",
  "pong",
  "keepalive",
  "heartbeat",
  "open",
  "close",
  "stream_error",
]);

function isControl(eventType: string): boolean {
  return CONTROL_TYPES.has(eventType.toLowerCase());
}

function eventIdOf(data: RawData): string | null {
  const id = (data as { event_id?: unknown }).event_id;
  return typeof id === "string" && id ? id : null;
}

function rowLevel(canonical: string): EventLevel {
  if (canonical.endsWith(".failed") || canonical === "task.cancelled")
    return "error";
  if (canonical.endsWith(".completed") || canonical.endsWith(".response"))
    return "success";
  if (canonical.endsWith(".request")) return "warning";
  return "info";
}

function rowDescription(canonical: string, data: RawData): string {
  const message = data.message ?? data.result ?? data.error;
  if (typeof message === "string" && message) return message;
  const toolName = data.tool_name ?? data.skill_name ?? data.script_name;
  if (typeof toolName === "string" && toolName) return toolName;
  return canonical;
}

/** Build an append-only debug row from a normalized event. */
function toDisplayRow(
  eventType: string,
  data: RawData,
  index: number
): DisplayEvent {
  const canonical = canonicalType(eventType);
  const rawTs =
    (typeof data.timestamp === "string" && data.timestamp) ||
    (typeof data.original_timestamp === "string" && data.original_timestamp) ||
    null;
  const ts = rawTs ? new Date(rawTs) : new Date();
  const id =
    (typeof data.event_id === "string" && data.event_id) ||
    `${canonical}-${index}`;
  return {
    id,
    type: canonical as WorkflowEventType,
    timestamp: Number.isNaN(ts.getTime()) ? new Date() : ts,
    title: canonical,
    description: rowDescription(canonical, data),
    level: rowLevel(canonical),
    data,
  };
}

/** The first unresolved input/approval form part, if any. */
function findPendingForm(parts: Part[]): Part | null {
  for (const part of parts) {
    if (part.kind !== "form") continue;
    if (
      part.eventType === "input.request" ||
      part.eventType === "approval.request"
    ) {
      return part;
    }
  }
  return null;
}

export interface UseTaskEventsResult {
  parts: Part[];
  timeline: TimelineItem[];
  status: TaskStatus;
  pendingForm: Part | null;
  terminalMessage: string | null;
  rawEvents: DisplayEvent[];
  loading: boolean;
  error: string | null;
  connected: boolean;
  refresh: () => void;
}

export function useTaskEvents(
  agentId: string | null,
  taskId: string | null,
  options: { includeHistory?: boolean; autoConnect?: boolean } = {}
): UseTaskEventsResult {
  const { includeHistory = true, autoConnect = true } = options;

  const [state, setState] = useState<EventState>(initialState);
  const [rawEvents, setRawEvents] = useState<DisplayEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const stateRef = useRef<EventState>(state);
  stateRef.current = state;
  const rawRef = useRef<DisplayEvent[]>([]);
  const rawCountRef = useRef(0);
  const loadedHistory = useRef(false);
  // Event ids already folded in — makes SSE reconnect replays (catch-up resends
  // the whole history) idempotent instead of duplicating every row.
  const seenIds = useRef<Set<string>>(new Set());
  const terminalReachedRef = useRef(false);
  // Live events that arrived while the history fetch was still in flight.
  const pendingLive = useRef<EventInput[]>([]);
  const historySettled = useRef(false);
  const disconnectRef = useRef<() => void>(() => {});

  const pushRaw = useCallback((eventType: string, data: RawData) => {
    const row = toDisplayRow(eventType, data, rawCountRef.current++);
    rawRef.current = [...rawRef.current, row];
    setRawEvents(rawRef.current);
  }, []);

  const applyOne = useCallback(
    (event: EventInput) => {
      const data = event.data as RawData;
      const id = eventIdOf(data);
      if (id) {
        if (seenIds.current.has(id)) return;
        seenIds.current.add(id);
      }
      const next = applyEvent(stateRef.current, event);
      stateRef.current = next;
      setState(next);
      pushRaw(event.eventType, data);
    },
    [pushRaw]
  );

  const push = useCallback(
    (event: EventInput) => {
      if (isControl(event.eventType)) return;
      // History is the older half of this same stream. Folding a live event in
      // before it lands would order it wrong and — worse — the history fold
      // rebuilds state from scratch, so the live event would be silently
      // dropped while its id stayed in seenIds, making it unrecoverable.
      if (includeHistory && !historySettled.current) {
        pendingLive.current.push(event);
        return;
      }
      applyOne(event);
    },
    [applyOne, includeHistory]
  );

  const sseUrl =
    agentId && taskId && autoConnect
      ? `/api/sse/agents/${agentId}/tasks/${taskId}/events/stream`
      : null;

  const handleSSEMessage = useCallback(
    (sseEvent: { type: string; data: unknown }) => {
      const normalized = normalizeSSEEvent(sseEvent.type, sseEvent.data);
      if (!normalized) return;
      push(normalized);
      if (isTerminal(normalized.eventType)) {
        terminalReachedRef.current = true;
        disconnectRef.current();
      }
    },
    [push]
  );

  const { isConnected, disconnect } = useSSE(sseUrl, {
    onMessage: handleSSEMessage,
    reconnect: true,
    reconnectInterval: 3000,
  });

  useEffect(() => {
    disconnectRef.current = disconnect;
  }, [disconnect]);

  useEffect(() => {
    terminalReachedRef.current = false;
    loadedHistory.current = false;
    historySettled.current = false;
    pendingLive.current = [];
    seenIds.current = new Set();
    rawRef.current = [];
    rawCountRef.current = 0;
    setRawEvents([]);
    stateRef.current = initialState();
    setState(stateRef.current);
  }, [agentId, taskId]);

  useEffect(() => {
    if (!agentId || !taskId || !includeHistory || loadedHistory.current) {
      // A run cancelled mid-flight never reaches its finally, so clear the
      // flag here — otherwise flipping includeHistory off during a fetch
      // leaves the consumer loading forever.
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    void (async () => {
      try {
        const result = await getTaskEvents(agentId, taskId, {
          page: 1,
          page_size: 100,
        });
        const data = result.data;
        if (result.error || !data) {
          throw new Error(apiErrorMessage(result, "Failed to load events"));
        }
        if (cancelled) return;

        let next = initialState();
        const rows: DisplayEvent[] = [];
        // Ids are held back until the fold is committed below. Marking one seen
        // while its event is still only in a local `next` would strand it if
        // this loop threw: applied nowhere, yet skipped forever after.
        const foldedIds: string[] = [];
        for (const event of data.events) {
          const input = normalizeHistory(event);
          if (isControl(input.eventType)) continue;
          const id = eventIdOf(input.data as RawData);
          if (id) {
            if (seenIds.current.has(id) || foldedIds.includes(id)) continue;
            foldedIds.push(id);
          }
          next = applyEvent(next, input);
          rows.push(
            toDisplayRow(input.eventType, input.data as RawData, rows.length)
          );
        }
        for (const id of foldedIds) seenIds.current.add(id);
        stateRef.current = next;
        rawRef.current = rows;
        rawCountRef.current = rows.length;
        loadedHistory.current = true;
        setState(next);
        setRawEvents(rows);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load events");
      } finally {
        if (!cancelled) {
          // Replay whatever streamed in while the fetch was running, in arrival
          // order and after history. Also runs on failure: a task whose history
          // could not load must still show live events rather than stall.
          historySettled.current = true;
          const buffered = pendingLive.current;
          pendingLive.current = [];
          for (const event of buffered) applyOne(event);
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [agentId, taskId, includeHistory, nonce, applyOne]);

  const refresh = useCallback(() => {
    loadedHistory.current = false;
    // Buffer live events again: refresh re-runs the history fold, which rebuilds
    // state from scratch and would otherwise drop anything streaming in now.
    historySettled.current = false;
    pendingLive.current = [];
    seenIds.current = new Set();
    rawRef.current = [];
    rawCountRef.current = 0;
    setRawEvents([]);
    stateRef.current = initialState();
    setState(stateRef.current);
    setNonce((n) => n + 1);
  }, []);

  return {
    parts: state.parts,
    timeline: state.timeline,
    status: state.status,
    pendingForm: findPendingForm(state.parts),
    terminalMessage: state.terminalMessage,
    rawEvents,
    loading,
    error,
    connected: isConnected,
    refresh,
  };
}
