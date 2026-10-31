// Folds stopped runs that failed the same way into one row, so a burst of
// identical failures reads as one problem with a count.

type StoppedRun = {
  task_id: string;
  agent_id: string;
  error: string | null;
  occurred_at: string;
  description?: string;
};

export type StoppedKind = "blocked" | "failed";

export type StoppedGroup<T> = {
  key: string;
  kind: StoppedKind;
  /** The most recent run of the group; the row links to it. */
  latest: T;
  count: number;
  /** First line of the error, else the run's description. */
  reason: string | null;
};

export function firstLine(text: string | null | undefined): string | null {
  return text?.split("\n")[0] || null;
}

/** One group per kind, agent and reason, the most recent first. */
export function groupStopped<B extends StoppedRun, F extends StoppedRun>(
  blocked: B[],
  failed: F[]
): StoppedGroup<B | F>[] {
  const groups = new Map<string, StoppedGroup<B | F>>();
  const add = (kind: StoppedKind, run: B | F) => {
    const reason = firstLine(run.error) || run.description || null;
    const key = [kind, run.agent_id, reason ?? ""].join("\u0000");
    const group = groups.get(key);
    if (!group) {
      groups.set(key, { key, kind, latest: run, count: 1, reason });
      return;
    }
    group.count += 1;
    if (Date.parse(run.occurred_at) > Date.parse(group.latest.occurred_at)) {
      group.latest = run;
    }
  };
  blocked.forEach((run) => add("blocked", run));
  failed.forEach((run) => add("failed", run));
  return [...groups.values()].sort(
    (a, b) =>
      Date.parse(b.latest.occurred_at) - Date.parse(a.latest.occurred_at)
  );
}
