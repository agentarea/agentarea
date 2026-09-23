import type { TaskEvent, TaskEventResponse } from "@/api/client";

type TaskEventPage = Pick<TaskEventResponse, "events" | "has_next">;

export class TaskEventsHistoryError extends Error {
  constructor(readonly result: unknown) {
    super("Failed to load task events");
    this.name = "TaskEventsHistoryError";
  }
}

/** Load every history page in chronological API order. */
export async function loadAllTaskEventPages(
  fetchPage: (page: number, pageSize: number) => Promise<{
    data?: TaskEventPage | null;
    error?: unknown;
  }>,
  pageSize = 100,
  shouldStop: () => boolean = () => false
): Promise<TaskEvent[] | null> {
  if (pageSize <= 0) throw new Error("Invalid task event page size");
  const events: TaskEvent[] = [];
  let page = 1;

  while (true) {
    if (shouldStop()) return null;
    const result = await fetchPage(page, pageSize);
    if (result.error || !result.data) {
      throw new TaskEventsHistoryError(result);
    }

    events.push(...result.data.events);
    if (!result.data.has_next) return events;
    if (result.data.events.length === 0) {
      throw new TaskEventsHistoryError({
        error: "Task event history pagination returned an empty page",
      });
    }
    page += 1;
  }
}
