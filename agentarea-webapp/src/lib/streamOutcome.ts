/**
 * What a stream event led to, from the outcomes its subscribers recorded. An
 * event with no outcome is "unheard": nothing listened, which is a fact worth
 * showing rather than an absence.
 */

export type Disposition = "error" | "reacted" | "skipped" | "unheard";
export type DispositionFilter = Disposition | "all";

export type OutcomeSummary = {
  reacted: number;
  skipped: number;
  error: number;
  total: number;
};

export function summarizeOutcomes(
  outcomes: ReadonlyArray<{ verdict: string }>
): OutcomeSummary {
  const summary: OutcomeSummary = {
    reacted: 0,
    skipped: 0,
    error: 0,
    total: 0,
  };
  for (const { verdict } of outcomes) {
    if (verdict === "reacted" || verdict === "skipped" || verdict === "error") {
      summary[verdict] += 1;
    }
    summary.total += 1;
  }
  return summary;
}

export function eventDisposition(summary: OutcomeSummary): Disposition {
  if (summary.total === 0) return "unheard";
  if (summary.error > 0) return "error";
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
