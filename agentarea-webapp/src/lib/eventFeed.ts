import type {
  FeedEventResponse,
  Processing,
  ProcessingStatus,
} from "@/api/client/types.gen";
import { getTaskStatusPresentation, type StatusKind } from "@/lib/status";
import { parseUtcTimestamp } from "@/utils/dateUtils";

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
  /** `0` leaves out the platform's own events, which the feed shows by default. */
  platform?: "0";
}

/** The source type of the events the platform writes about its own tasks. */
export const PLATFORM_SOURCE_TYPE = "platform";

const KEYS = [
  "stream",
  "source_type",
  "kind",
  "result",
  "session",
  "sender",
  "event",
  "before",
  "platform",
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
    } else if (key === "platform") {
      if (value === "0") state.platform = value;
    } else {
      state[key] = value;
    }
  }
  return state;
}

/**
 * A feed URL; `patch` replaces values, an `undefined` in it removes one. A
 * stream is the path, `/events/{stream}`, not a filter in the query.
 */
export function feedHref(state: FeedState, patch: Partial<FeedState> = {}) {
  const merged: FeedState = { ...state, ...patch };
  const params = new URLSearchParams();
  for (const key of KEYS) {
    const value = merged[key];
    if (value && key !== "stream") params.set(key, value);
  }
  const query = params.toString();
  const path = merged.stream
    ? `/events/${encodeURIComponent(merged.stream)}`
    : "/events";
  return `${path}${query ? `?${query}` : ""}`;
}

/** An event by its id, opened in the feed of whichever stream holds it. */
export function eventByIdHref(eventId: string): string {
  return `/events/event/${encodeURIComponent(eventId)}`;
}

const LEGACY_OUTCOMES: Record<string, ProcessingStatus | undefined> = {
  all: undefined,
  reacted: "handled",
  skipped: "skipped",
  error: "error",
  unheard: "no_handlers",
};

/**
 * What a stream page URL from before the shared feed asked for: its
 * `?outcome=` as a result, and its `?event=` as a sequence. Null when the URL
 * carries neither.
 */
export function legacyStreamQuery(
  params: Record<string, string | string[] | undefined>
): { result?: ProcessingStatus; sequence?: number } | null {
  const outcome = typeof params.outcome === "string" ? params.outcome : null;
  const event = typeof params.event === "string" ? params.event : "";
  const sequence = /^\d+$/.test(event) ? Number(event) : undefined;
  if (outcome === null && sequence === undefined) return null;
  const result = outcome === null ? undefined : LEGACY_OUTCOMES[outcome];
  return {
    ...(result ? { result } : {}),
    ...(sequence !== undefined ? { sequence } : {}),
  };
}

/** The view is the platform's own: its stream or its provider is the filter. */
export function platformForced(
  state: FeedState,
  platformStreams: readonly string[]
): boolean {
  return (
    state.source_type === PLATFORM_SOURCE_TYPE ||
    (state.stream !== undefined && platformStreams.includes(state.stream))
  );
}

/** Whether the feed shows the platform's own events. */
export function showsPlatform(
  state: FeedState,
  platformStreams: readonly string[]
): boolean {
  return state.platform !== "0" || platformForced(state, platformStreams);
}

/** The feed's filters as the API names them. */
export function feedApiQuery(state: FeedState, showPlatform: boolean) {
  return {
    stream_id: state.stream,
    source_type: state.source_type,
    kind: state.kind,
    result: state.result,
    session_key: state.session,
    sender: state.sender,
    platform: showPlatform ? undefined : false,
  };
}

/**
 * The live tail's query: the feed's filters but the result, which changes as
 * an event is handled and is applied here instead (`matchesResult`).
 */
export function liveQuery(state: FeedState, showPlatform: boolean): string {
  const { result: _result, ...rest } = feedApiQuery(state, showPlatform);
  return Object.entries(rest)
    .filter(
      (entry): entry is [string, string | boolean] =>
        entry[1] !== undefined && entry[1] !== ""
    )
    .map(
      ([key, value]) =>
        `${key}=${encodeURIComponent(String(value)).replace(/%2A/g, "*")}`
    )
    .join("&");
}

export function matchesResult(
  event: FeedEventResponse,
  result: ProcessingStatus | undefined
): boolean {
  return result === undefined || event.processing.status === result;
}

/** A result a row shows as its glyph alone: nothing in it asks to be read. */
export function rowStatusQuiet(status: ProcessingStatus): boolean {
  return (
    status === "no_handlers" || status === "skipped" || status === "handled"
  );
}

/** What became of an event, as its row says it. */
export type EventFate =
  | { key: "queued" | "processing" | "nobody" | "skipped" | "passedOn" }
  | { key: "failed"; count: number }
  | { key: "tasks"; count: number; status: StatusKind };

const TASK_URGENCY: StatusKind[] = ["failed", "attention", "running", "queued"];

export function eventFate(p: Processing): EventFate {
  switch (p.status) {
    case "queued":
    case "processing":
      return { key: p.status };
    case "no_handlers":
      return { key: "nobody" };
    case "skipped":
      return { key: "skipped" };
    case "error":
      return { key: "failed", count: p.errors };
  }
  const tasks = p.tasks ?? [];
  if (tasks.length === 0) return { key: "passedOn" };
  const kinds = tasks.map((t) => getTaskStatusPresentation(t.status).kind);
  const status = TASK_URGENCY.find((k) => kinds.includes(k)) ?? "done";
  return { key: "tasks", count: tasks.length, status };
}

/** An event the feed shows, with the alike events right after it that it stands for. */
export interface FeedItem {
  event: FeedEventResponse;
  folded: FeedEventResponse[];
}

function runKey(e: FeedEventResponse): string {
  return JSON.stringify([
    e.stream_id,
    e.kind,
    e.summary,
    e.sender,
    eventFate(e.processing),
  ]);
}

/**
 * Neighbours from one stream that say and came to the same, as one item: the
 * newest with the rest folded under it. A run with an event in `open` stays
 * unfolded.
 */
export function foldRuns(
  events: readonly FeedEventResponse[],
  open: ReadonlySet<string>
): FeedItem[] {
  const runs: FeedEventResponse[][] = [];
  let key = "";
  for (const event of events) {
    const k = runKey(event);
    if (runs.length > 0 && k === key) runs[runs.length - 1].push(event);
    else runs.push([event]);
    key = k;
  }
  return runs.flatMap((run) =>
    run.some((e) => open.has(e.event_id))
      ? run.map((event) => ({ event, folded: [] }))
      : [{ event: run[0], folded: run.slice(1) }]
  );
}

const PLATFORM_OUTCOMES: Record<
  string,
  {
    key: "completed" | "failed" | "cancelled" | "approval" | "input";
    status: StatusKind;
  }
> = {
  "task.completed": { key: "completed", status: "done" },
  "task.failed": { key: "failed", status: "failed" },
  "task.cancelled": { key: "cancelled", status: "cancelled" },
  "approval.requested": { key: "approval", status: "attention" },
  "input.request": { key: "input", status: "attention" },
};

/** What a platform event says about its task; null for a kind the platform does not write. */
export function platformOutcome(kind: string) {
  return PLATFORM_OUTCOMES[kind] ?? null;
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

export type EventTimeStyle = "time" | "dateTime" | "full";

const EVENT_TIME_FORMATS: Record<EventTimeStyle, Intl.DateTimeFormatOptions> = {
  time: { hour: "2-digit", minute: "2-digit" },
  dateTime: { dateStyle: "medium", timeStyle: "short" },
  // `timeStyle: "long"` carries the zone's name; `timeZoneName` cannot be
  // combined with a style.
  full: { dateStyle: "medium", timeStyle: "long" },
};

/** An event's time in `zone`; "—" when it is not a time. */
export function formatEventTime(
  iso: string,
  locale: string,
  zone: string,
  style: EventTimeStyle
): string {
  const date = parseUtcTimestamp(iso);
  if (!date) return "—";
  return date.toLocaleString(locale, {
    ...EVENT_TIME_FORMATS[style],
    timeZone: zone,
  });
}

/** The full time in `zone`, then in UTC unless that is the zone. */
export function utcTitle(iso: string, locale: string, zone: string): string {
  const local = formatEventTime(iso, locale, zone, "full");
  if (zone === "UTC") return local;
  return `${local} · ${formatEventTime(iso, locale, "UTC", "full")}`;
}
