import type { FrequentSchedule, ScheduledRun } from "@/api/client";

/** One thing that will start: a trigger's next firing or a task booked for later. */
export type ExpectedRun = {
  id: string;
  firesAt: string;
  title: string;
  agentId: string;
  agentName: string | null;
  triggerId: string | null;
  taskId: string | null;
};

/**
 * What will start next, soonest first: each trigger once, by its next firing
 * (frequent ones included), and every task booked for later.
 */
export function expectedRuns(
  runs: ScheduledRun[],
  frequent: FrequentSchedule[],
  now: Date
): ExpectedRun[] {
  const out: ExpectedRun[] = [];
  const seen = new Set<string>();
  const ahead = [...runs]
    .filter((r) => new Date(r.fires_at) >= now)
    .sort((a, b) => a.fires_at.localeCompare(b.fires_at));
  for (const r of ahead) {
    if (r.trigger_id) {
      if (seen.has(r.trigger_id)) continue;
      seen.add(r.trigger_id);
    }
    out.push({
      id: r.task_id ?? `trigger-${r.trigger_id}`,
      firesAt: r.fires_at,
      title: r.title,
      agentId: r.agent_id,
      agentName: r.agent_name ?? null,
      triggerId: r.trigger_id ?? null,
      taskId: r.task_id ?? null,
    });
  }
  for (const f of frequent) {
    if (seen.has(f.trigger_id)) continue;
    seen.add(f.trigger_id);
    out.push({
      id: `trigger-${f.trigger_id}`,
      firesAt: f.next_run_at,
      title: f.title,
      agentId: f.agent_id,
      agentName: f.agent_name ?? null,
      triggerId: f.trigger_id,
      taskId: null,
    });
  }
  return out.sort((a, b) => a.firesAt.localeCompare(b.firesAt));
}
