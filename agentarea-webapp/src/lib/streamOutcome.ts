/**
 * What a stream event led to, from the outcomes its subscribers recorded. An
 * event with no outcome is "unheard": nothing listened, which is a fact worth
 * showing rather than an absence. A verdict this build does not know is
 * "unknown" and outranks a reaction: it may be a failure, so it is never read
 * as fine.
 */

export type Disposition =
  | "error"
  | "unknown"
  | "reacted"
  | "skipped"
  | "unheard";
export type DispositionFilter = Disposition | "all";

export type OutcomeSummary = {
  reacted: number;
  skipped: number;
  error: number;
  unknown: number;
  total: number;
};

export function summarizeOutcomes(
  outcomes: ReadonlyArray<{ verdict: string }>
): OutcomeSummary {
  const summary: OutcomeSummary = {
    reacted: 0,
    skipped: 0,
    error: 0,
    unknown: 0,
    total: 0,
  };
  for (const { verdict } of outcomes) {
    if (verdict === "reacted" || verdict === "skipped" || verdict === "error") {
      summary[verdict] += 1;
    } else {
      summary.unknown += 1;
    }
    summary.total += 1;
  }
  return summary;
}

export function eventDisposition(summary: OutcomeSummary): Disposition {
  if (summary.total === 0) return "unheard";
  if (summary.error > 0) return "error";
  if (summary.unknown > 0) return "unknown";
  if (summary.reacted > 0) return "reacted";
  return "skipped";
}

export function matchesDisposition(
  outcomes: ReadonlyArray<{ verdict: string }>,
  filter: DispositionFilter
): boolean {
  return (
    filter === "all" || eventDisposition(summarizeOutcomes(outcomes)) === filter
  );
}

/**
 * Where a forwarded event came from, parsed from its own `source` and
 * `event_key` — both set deterministically by `ForwardHandler` (forward.py:
 * `source=f"stream:{event.stream_id}"`, `event_key=f"{event.stream_id}:{event.sequence}"`).
 * An event nothing forwarded (no `causation_id`) has no causing event to
 * resolve; `causation_id` is only ever set by that handler.
 */
export function resolveForwardSource(event: {
  causation_id: string | null;
  source: string;
  event_key: string;
}): { streamId: string; sequence: number } | null {
  if (!event.causation_id) return null;
  const sourceMatch = /^stream:(.+)$/.exec(event.source);
  if (!sourceMatch) return null;
  const sequenceMatch = /:(\d+)$/.exec(event.event_key);
  if (!sequenceMatch) return null;
  return { streamId: sourceMatch[1], sequence: Number(sequenceMatch[1]) };
}

/**
 * A forward's output streams, in the order `ForwardHandler` appended derived
 * events (`for output in sorted(subscription.output_stream_ids)`) — so
 * `outcome.derived_sequences[i]` landed in this array's `i`-th stream.
 */
export function sortedForwardTargets(
  outputStreamIds: readonly string[]
): string[] {
  return [...outputStreamIds].sort();
}
