import { getTaskStatusPresentation } from "@/lib/status";

// Buckets for the agent detail page, read off the shared task-status
// presentation so a status is classified the same way it is drawn. Shared
// between the overview body and the tab bar so the running count matches.

/** Actually executing. Queued work (`pending`/`submitted`) is not — the
 * overview lists it under Upcoming, and counting it here too shows one run
 * twice. */
export function isRunningTask(task: { status?: string | null }): boolean {
  return (
    getTaskStatusPresentation(String(task.status ?? "")).labelKey === "running"
  );
}

/** Parked on a person: an answer or an approval. */
export function isAwaitingUserTask(task: { status?: string | null }): boolean {
  const { labelKey } = getTaskStatusPresentation(String(task.status ?? ""));
  return labelKey === "inputRequired" || labelKey === "approvalRequired";
}
