import type { DispositionFilter } from "@/lib/streamOutcome";

/** A stream feed URL; "all" and absent values stay out of the query. */
export function feedHref(
  streamId: string,
  state: { outcome: DispositionFilter; before?: number; event?: number }
): string {
  const params = new URLSearchParams();
  if (state.outcome !== "all") params.set("outcome", state.outcome);
  if (state.before !== undefined) params.set("before", String(state.before));
  if (state.event !== undefined) params.set("event", String(state.event));
  const query = params.toString();
  return `/events/${streamId}${query ? `?${query}` : ""}`;
}
