"use server";

import { getAllTasks, resolvePrincipals, type TaskWithAgent } from "@/lib/api";
import { pageWindow, takePage } from "@/lib/offsetPage";
import { getTaskSource } from "@/lib/taskSource";
import type { TaskStatusValue } from "@/lib/taskStatusFilter";

const TASKS_PAGE_SIZE = 50;

export interface TasksQuery {
  statuses: TaskStatusValue[];
  search: string;
  /** tasks.created_by to narrow the list to, from the "Started by" cell's link. */
  creator: string;
}

export interface TasksPageResult {
  tasks: TaskWithAgent[];
  hasNext: boolean;
  /**
   * Principal id -> display name for the ids these rows mention. An id the
   * backend cannot resolve is absent, and the cell renders it as unknown.
   */
  principalNames: Record<string, string>;
}

/** One page of the workspace's tasks, newest first; null when it failed. */
export async function fetchTasksPage(
  query: TasksQuery,
  page: number
): Promise<TasksPageResult | null> {
  try {
    return await loadTasksPage(query, page);
  } catch {
    return null;
  }
}

async function loadTasksPage(
  query: TasksQuery,
  page: number
): Promise<TasksPageResult | null> {
  const { data, error } = await getAllTasks({
    ...pageWindow(page, TASKS_PAGE_SIZE),
    status: query.statuses.length > 0 ? query.statuses : undefined,
    search: query.search.trim() || undefined,
    created_by: query.creator.trim() || undefined,
  });
  if (error || !data) return null;
  const { rows: tasks, hasNext } = takePage(data, TASKS_PAGE_SIZE);

  // Joined here rather than served alongside each task: only the rows actually
  // being rendered need a name, and distinct principals are usually a handful
  // even on a full page.
  //
  // Both kinds of principal a row can mention go in one batch: the task's own
  // creator, and whatever its source points at — for a delegated task, the
  // agent that delegated it.
  const principals = await resolvePrincipals([
    ...new Set(
      tasks
        .flatMap((task) => [
          task.created_by,
          getTaskSource(task.parameters ?? undefined).principalId,
        ])
        .filter((id): id is string => Boolean(id))
    ),
  ]);
  const principalNames = Object.fromEntries(
    (principals.data ?? [])
      .filter((principal) => principal.display_name)
      .map((principal) => [principal.id, principal.display_name as string])
  );

  return { tasks, hasNext, principalNames };
}
