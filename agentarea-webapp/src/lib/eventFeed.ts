import type {
  FeedEventResponse,
  Processing,
  ProcessingStatus,
} from "@/api/client/types.gen";

/** What the platform did with an event, as the feed filters it. */
export const PROCESSING_RESULTS: readonly ProcessingStatus[] = [
  "queued",
  "processing",
  "handled",
  "error",
  "no_handlers",
  "skipped",
];

/** The workspace feed's view, all of it in the URL. */
export interface FeedState {
  stream?: string;
  source_type?: string;
  kind?: string;
  result?: ProcessingStatus;
  session?: string;
  sender?: string;
  /** The event open in the side panel. */
  event?: string;
  /** An older page: the sequence it starts before. */
  before?: string;
}

const KEYS = [
  "stream",
  "source_type",
  "kind",
  "result",
  "session",
  "sender",
  "event",
  "before",
] as const;

export function parseFeedState(
  params: Record<string, string | string[] | undefined>
): FeedState {
  const state: FeedState = {};
  for (const key of KEYS) {
    const value = params[key];
    if (typeof value !== "string" || value === "") continue;
    if (key === "result") {
      const result = PROCESSING_RESULTS.find((r) => r === value);
      if (result) state.result = result;
    } else {
      state[key] = value;
    }
  }
  return state;
}

/** A feed URL; `patch` replaces values, an `undefined` in it removes one. */
export function feedHref(state: FeedState, patch: Partial<FeedState> = {}) {
  const merged: FeedState = { ...state, ...patch };
  const params = new URLSearchParams();
  for (const key of KEYS) {
    const value = merged[key];
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return `/events${query ? `?${query}` : ""}`;
}

/** The feed's filters as the API names them. */
export function feedApiQuery(state: FeedState) {
  return {
    stream_id: state.stream,
    source_type: state.source_type,
    kind: state.kind,
    result: state.result,
    session_key: state.session,
    sender: state.sender,
  };
}

/**
 * The live tail's query: the feed's filters but the result, which changes as
 * an event is handled and is applied here instead (`matchesResult`).
 */
export function liveQuery(state: FeedState): string {
  const { result: _result, ...rest } = feedApiQuery(state);
  return Object.entries(rest)
    .filter((entry): entry is [string, string] => Boolean(entry[1]))
    .map(
      ([key, value]) =>
        `${key}=${encodeURIComponent(value).replace(/%2A/g, "*")}`
    )
    .join("&");
}

export function matchesResult(
  event: FeedEventResponse,
  result: ProcessingStatus | undefined
): boolean {
  return result === undefined || event.processing.status === result;
}

export interface ProcessingProgress {
  done: number;
  total: number;
  tasks: number;
  skipped: number;
  errors: number;
}

export function processingProgress(p: Processing): ProcessingProgress {
  return {
    done: p.reacted,
    total: Math.max(p.subscribers ?? 0, p.reacted),
    tasks: p.tasks?.length ?? 0,
    skipped: p.skipped,
    errors: p.errors,
  };
}

/** An event that arrived live: on top once, by sequence; a repeat takes its newer state. */
export function applyRecorded(
  events: FeedEventResponse[],
  item: FeedEventResponse
): FeedEventResponse[] {
  const index = events.findIndex((e) => e.event_id === item.event_id);
  if (index >= 0) {
    const known = events[index];
    if (
      known.processing.status === item.processing.status &&
      known.processing.reacted === item.processing.reacted &&
      (known.processing.tasks?.length ?? 0) ===
        (item.processing.tasks?.length ?? 0)
    ) {
      return events;
    }
    return events.map((e, i) => (i === index ? item : e));
  }
  const next = [...events, item];
  next.sort((a, b) => b.sequence - a.sequence);
  return next;
}

export function applyProcessing(
  events: FeedEventResponse[],
  eventId: string,
  processing: Processing
): FeedEventResponse[] {
  if (!events.some((e) => e.event_id === eventId)) return events;
  return events.map((e) => (e.event_id === eventId ? { ...e, processing } : e));
}

export interface DayGroup {
  /** `YYYY-MM-DD` in the viewer's zone. */
  day: string;
  relative: "today" | "yesterday" | null;
  events: FeedEventResponse[];
}

function dayKey(date: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

/** The events by the day they arrived in `timeZone`, in the order given. */
export function dayGroups(
  events: FeedEventResponse[],
  now: Date,
  timeZone: string
): DayGroup[] {
  const today = dayKey(now, timeZone);
  const yesterday = dayKey(new Date(now.getTime() - 86_400_000), timeZone);
  const groups: DayGroup[] = [];
  for (const event of events) {
    const day = dayKey(new Date(event.received_at), timeZone);
    let group = groups[groups.length - 1];
    if (!group || group.day !== day) {
      group = {
        day,
        relative:
          day === today ? "today" : day === yesterday ? "yesterday" : null,
        events: [],
      };
      groups.push(group);
    }
    group.events.push(event);
  }
  return groups;
}

/** The event `step` rows away from `current`; the first one when nothing is open. */
export function neighbourEvent(
  events: FeedEventResponse[],
  current: string | undefined,
  step: 1 | -1
): string | undefined {
  if (current === undefined) return events[0]?.event_id;
  const index = events.findIndex((e) => e.event_id === current);
  if (index < 0) return events[0]?.event_id;
  return events[index + step]?.event_id;
}

/** A wait as one short unit: `3s`, `2m`, `3h`, `2d`. */
export function shortAge(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}
