// Task statuses that count as "in progress" on the agent detail page — shared
// between the overview body and the tab bar so the running count matches.
export const RUNNING_TASK_STATUSES = new Set([
  "running",
  "working",
  "submitted",
  "in_progress",
]);

export function isRunningTask(task: { status?: string | null }): boolean {
  return RUNNING_TASK_STATUSES.has(String(task.status ?? ""));
}
