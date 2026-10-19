import type {
  FeedEventResponse,
  ProcessingStatus,
} from "@/api/client/types.gen";
import type { FeedState } from "@/lib/eventFeed";

/** The source type of what the platform writes to a workspace's platform stream. */
export const PLATFORM_SOURCE_TYPE = "platform";

/** Worst first: the status a run of events shows for all of them. */
const SEVERITY: readonly ProcessingStatus[] = [
  "error",
  "processing",
  "queued",
  "handled",
  "skipped",
  "no_handlers",
];

export interface KindCount {
  kind: string;
  count: number;
}

/** Consecutive platform events, folded into one row of the feed. */
export interface PlatformRun {
  /** Keyed by its oldest event, which stays put while newer ones join on top. */
  id: string;
  /** In the feed's order, newest first. */
  events: FeedEventResponse[];
  kinds: KindCount[];
  worst: ProcessingStatus;
  /** How many of the events have the worst status. */
  worstCount: number;
  oldest: string;
  newest: string;
}

export type FeedItem =
  | { type: "event"; event: FeedEventResponse }
  | { type: "run"; run: PlatformRun };

export type FeedStop = { type: "event" | "run"; id: string };

export function isPlatformEvent(event: FeedEventResponse): boolean {
  return event.source_type === PLATFORM_SOURCE_TYPE;
}

function severity(status: ProcessingStatus): number {
  const index = SEVERITY.indexOf(status);
  return index < 0 ? SEVERITY.length : index;
}

/** error > processing > queued > handled > skipped > no handlers. */
export function worstStatus(
  events: readonly FeedEventResponse[]
): ProcessingStatus | undefined {
  let worst: ProcessingStatus | undefined;
  for (const event of events) {
    const status = event.processing.status;
    if (worst === undefined || severity(status) < severity(worst)) {
      worst = status;
    }
  }
  return worst;
}

/** How many events of each kind, the commonest first. */
export function kindBreakdown(
  events: readonly FeedEventResponse[]
): KindCount[] {
  const counts = new Map<string, number>();
  for (const event of events) {
    counts.set(event.kind, (counts.get(event.kind) ?? 0) + 1);
  }
  return [...counts]
    .map(([kind, count]) => ({ kind, count }))
    .sort((a, b) => b.count - a.count || a.kind.localeCompare(b.kind));
}

function platformRun(events: FeedEventResponse[]): PlatformRun {
  const worst = worstStatus(events) ?? "no_handlers";
  return {
    id: `run-${events[events.length - 1].event_id}`,
    events,
    kinds: kindBreakdown(events),
    worst,
    worstCount: events.filter((e) => e.processing.status === worst).length,
    oldest: events[events.length - 1].received_at,
    newest: events[0].received_at,
  };
}

/**
 * The feed's rows: every two or more platform events in a row fold into one
 * run; a lone one, and everything else, stays an event.
 */
export function feedItems(
  events: readonly FeedEventResponse[],
  group: boolean
): FeedItem[] {
  const items: FeedItem[] = [];
  let pending: FeedEventResponse[] = [];
  const flush = () => {
    if (pending.length > 1) {
      items.push({ type: "run", run: platformRun(pending) });
    } else if (pending.length === 1) {
      items.push({ type: "event", event: pending[0] });
    }
    pending = [];
  };
  for (const event of events) {
    if (group && isPlatformEvent(event)) {
      pending.push(event);
      continue;
    }
    flush();
    items.push({ type: "event", event });
  }
  flush();
  return items;
}

/** Folding is off once the filters already narrow the feed to platform events. */
export function groupsPlatformRuns(
  state: FeedState,
  platformStreamIds: readonly string[]
): boolean {
  if (state.source_type === PLATFORM_SOURCE_TYPE) return false;
  return !(state.stream && platformStreamIds.includes(state.stream));
}

/** Open when the viewer opened it or the selected event is in it. */
export function isRunExpanded(
  run: PlatformRun,
  opened: ReadonlySet<string>,
  selected: string | null | undefined
): boolean {
  return (
    opened.has(run.id) ||
    (selected != null && run.events.some((e) => e.event_id === selected))
  );
}

/** The run holding `eventId`, if it is folded into one. */
export function runHolding(
  items: readonly FeedItem[],
  eventId: string | null | undefined
): PlatformRun | undefined {
  if (eventId == null) return undefined;
  for (const item of items) {
    if (
      item.type === "run" &&
      item.run.events.some((e) => e.event_id === eventId)
    ) {
      return item.run;
    }
  }
  return undefined;
}

/** Where the arrow keys stop: each row, a run as one, then its events once open. */
export function feedStops(
  items: readonly FeedItem[],
  expanded: (run: PlatformRun) => boolean
): FeedStop[] {
  const stops: FeedStop[] = [];
  for (const item of items) {
    if (item.type === "event") {
      stops.push({ type: "event", id: item.event.event_id });
      continue;
    }
    stops.push({ type: "run", id: item.run.id });
    if (expanded(item.run)) {
      for (const event of item.run.events) {
        stops.push({ type: "event", id: event.event_id });
      }
    }
  }
  return stops;
}

/** The stop `step` away from `current`; the first one when there is none. */
export function neighbourStop(
  stops: readonly FeedStop[],
  current: FeedStop | undefined,
  step: 1 | -1
): FeedStop | undefined {
  const index = current
    ? stops.findIndex((s) => s.type === current.type && s.id === current.id)
    : -1;
  if (index < 0) return stops[0];
  return stops[index + step];
}
