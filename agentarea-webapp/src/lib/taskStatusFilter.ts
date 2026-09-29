/**
 * The task list's status filter, derived from the backend vocabulary.
 *
 * The list comes from the generated client, so a status the backend adds shows
 * up here without a hand edit. Statuses that read the same on screen (Pending,
 * Running) share one option and are filtered on together; every status lands
 * in exactly one option, so none becomes unfindable.
 */

import type { GetAllTasksV1TasksGetData } from "@/api/client";
import { zGetAllTasksV1TasksGetQuery } from "@/api/client/zod.gen";
import { getTaskStatusPresentation } from "./status";

export type TaskStatusValue = NonNullable<
  NonNullable<GetAllTasksV1TasksGetData["query"]>["status"]
>[number];

export const TASK_STATUS_VALUES: readonly TaskStatusValue[] =
  zGetAllTasksV1TasksGetQuery.shape.status.unwrap().unwrap().element.options;

export interface TaskStatusFilterOption {
  /** The status that names the option in the URL and renders its marker. */
  value: TaskStatusValue;
  statuses: TaskStatusValue[];
}

function presentationKey(status: TaskStatusValue): string {
  const presentation = getTaskStatusPresentation(status);
  return presentation.labelKey ?? presentation.label;
}

export const TASK_STATUS_FILTER_OPTIONS: readonly TaskStatusFilterOption[] =
  (() => {
    const groups = new Map<string, TaskStatusValue[]>();
    for (const status of TASK_STATUS_VALUES) {
      const key = presentationKey(status);
      groups.set(key, [...(groups.get(key) ?? []), status]);
    }
    return [...groups.entries()].map(([key, statuses]) => ({
      value: statuses.find((status) => status === key) ?? statuses[0],
      statuses,
    }));
  })();

function optionFor(status: string): TaskStatusFilterOption | null {
  return (
    TASK_STATUS_FILTER_OPTIONS.find((option) =>
      (option.statuses as string[]).includes(status)
    ) ?? null
  );
}

/** Every status the filter for `status` covers, or null for an unknown value. */
export function statusesForFilter(status: string): TaskStatusValue[] | null {
  const option = optionFor(status);
  return option ? [...option.statuses] : null;
}

/** The option a status is filed under, or null for an unknown value. */
export function filterValueFor(status: string): TaskStatusValue | null {
  return optionFor(status)?.value ?? null;
}
