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
  /** Any of these source types; never empty when set. */
  source_type?: string[];
  kind?: string;
  result?: ProcessingStatus;
  session?: string;
  sender?: string;
  /** The event open in the side panel. */
  event?: string;
  /** An older page: the sequence it starts before. */
  before?: string;
  /** Whose events: unset is the ones from outside, the platform's own left out. */
  origin?: Exclude<FeedOrigin, "outside">;
}

/**
 * Whose events the feed shows: what arrived from outside (the default), that
 * and the platform's own (its tasks' outcomes), or the platform's alone.
 */
export type FeedOrigin = "outside" | "all" | "platform";

export const FEED_ORIGINS: readonly FeedOrigin[] = [
  "outside",
  "all",
  "platform",
];

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
  "origin",
] as const;

const UUID =
  /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;

/** An old stream page's `?event=`: the event's sequence in that stream. */
export function legacyEventSequence(
  value: string | string[] | undefined
): number | undefined {
  return typeof value === "string" && /^\d+$/.test(value)
    ? Number(value)
    : undefined;
}

export function parseFeedState(
  params: Record<string, string | string[] | undefined>
): FeedState {
  const state: FeedState = {};
  for (const key of KEYS) {
    const value = params[key];
    if (key === "source_type") {
      const types = [...new Set([value ?? []].flat())].filter(Boolean);
      if (types.length > 0) state.source_type = types;
      continue;
    }
    if (typeof value !== "string" || value === "") continue;
    if (key === "result") {
      const result = PROCESSING_RESULTS.find((r) => r === value);
      if (result) state.result = result;
    } else if (key === "origin") {
      if (value === "all" || value === "platform") state.origin = value;
    } else if (key === "event") {
      // An event is named by its id; anything else (an old link's sequence)
      // opens nothing rather than failing the read.
      if (UUID.test(value)) state.event = value;
    } else {
      state[key] = value;
    }
  }
  return state;
}

/**
 * Where a feed lives: the workspace's (`/events`) or one stream's, whose page
 * pins the stream, so its URL never carries it.
 */
export interface FeedPath {
  base: string;
  pinned?: readonly (keyof FeedState)[];
}

export const WORKSPACE_FEED: FeedPath = { base: "/events" };

/** A feed URL; `patch` replaces values, an `undefined` in it removes one. */
export function feedHref(
  state: FeedState,
  patch: Partial<FeedState> = {},
  path: FeedPath = WORKSPACE_FEED
) {
  const merged: FeedState = { ...state, ...patch };
  const params = new URLSearchParams();
  for (const key of KEYS) {
    if (path.pinned?.includes(key)) continue;
    for (const value of [merged[key] ?? []].flat()) {
      if (value) params.append(key, value);
    }
  }
  const query = params.toString();
  return `${path.base}${query ? `?${query}` : ""}`;
}

/**
 * Whose events the view holds. The other filters can decide it: the
 * platform's stream, or the platform as the only source, holds nothing else;
 * the platform among other sources holds both.
 */
export function feedOrigin(
  state: FeedState,
  platformStreams: readonly string[]
): FeedOrigin {
  if (state.origin === "platform") return "platform";
  if (state.stream !== undefined && platformStreams.includes(state.stream)) {
    return "platform";
  }
  if (state.source_type?.includes(PLATFORM_SOURCE_TYPE)) {
    return state.source_type.length === 1 ? "platform" : "all";
  }
  return state.origin ?? "outside";
}

/** Whether the feed shows the platform's own events. */
export function showsPlatform(
  state: FeedState,
  platformStreams: readonly string[]
): boolean {
  return feedOrigin(state, platformStreams) !== "outside";
}

/**
 * The patch that switches the view to `origin`, dropping a stream or source
 * filter that would contradict it: the platform's stream away from it, the
 * platform as a source when its events are left out, any other source when
 * only the platform's are wanted.
 */
export function originPatch(
  state: FeedState,
  platformStreams: readonly string[],
  origin: FeedOrigin
): Partial<FeedState> {
  const onPlatformStream =
    state.stream !== undefined && platformStreams.includes(state.stream);
  const sources = (state.source_type ?? []).filter((slug) =>
    origin === "outside"
      ? slug !== PLATFORM_SOURCE_TYPE
      : origin === "platform"
        ? slug === PLATFORM_SOURCE_TYPE
        : true
  );
  return {
    origin: origin === "outside" ? undefined : origin,
    stream:
      onPlatformStream && origin !== "platform" ? undefined : state.stream,
    source_type: sources.length > 0 ? sources : undefined,
  };
}

/**
 * The sources the API is asked for. Only the platform's: its source alone.
 * Outside and platform with sources picked: those and the platform's, so the
 * picked ones are added to what was shown rather than replacing it.
 */
function apiSourceTypes(state: FeedState): string[] | undefined {
  if (state.origin === "platform") return [PLATFORM_SOURCE_TYPE];
  if (state.origin === "all" && state.source_type) {
    return [...new Set([...state.source_type, PLATFORM_SOURCE_TYPE])];
  }
  return state.source_type;
}

/** The feed's filters as the API names them. */
export function feedApiQuery(state: FeedState, showPlatform: boolean) {
  return {
    stream_id: state.stream,
    source_type: apiSourceTypes(state),
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
    .flatMap(([key, value]) =>
      [value ?? []].flat().map((one) => [key, one] as const)
    )
    .filter(([, value]) => value !== "")
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
