import type { DisplayEvent, EventLevel } from "@/types/events";

export type EventLevelFilter = EventLevel | "all";

/** The level filter's options, in menu order. */
export const EVENT_LEVEL_FILTERS: readonly EventLevelFilter[] = [
  "all",
  "info",
  "success",
  "warning",
  "error",
];

/** The name an event's type reads as on screen, when it has one. */
export type EventLabel = (type: string) => string | null;

/**
 * A case-insensitive match on the event's type — as named on screen or as
 * sent — its description, or its data.
 */
export function matchesEventSearch(
  event: DisplayEvent,
  search: string,
  labelOf?: EventLabel
) {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;
  return (
    event.type.toLowerCase().includes(needle) ||
    Boolean(labelOf?.(event.type)?.toLowerCase().includes(needle)) ||
    event.description.toLowerCase().includes(needle) ||
    JSON.stringify(event.data ?? {})
      .toLowerCase()
      .includes(needle)
  );
}

/**
 * The events the search matches, counted per level filter: what each option
 * of the level filter would show with the search as it is.
 */
export function countEventLevels(
  events: DisplayEvent[],
  search: string,
  labelOf?: EventLabel
): Record<EventLevelFilter, number> {
  const counts: Record<EventLevelFilter, number> = {
    all: 0,
    info: 0,
    success: 0,
    warning: 0,
    error: 0,
  };
  for (const event of events) {
    if (!matchesEventSearch(event, search, labelOf)) continue;
    counts.all += 1;
    counts[event.level] += 1;
  }
  return counts;
}

export function filterTaskEvents(
  events: DisplayEvent[],
  {
    level,
    search,
    labelOf,
  }: { level: EventLevelFilter; search: string; labelOf?: EventLabel }
): DisplayEvent[] {
  return events.filter(
    (event) =>
      (level === "all" || event.level === level) &&
      matchesEventSearch(event, search, labelOf)
  );
}
