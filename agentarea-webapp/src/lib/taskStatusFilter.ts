/**
 * The task list's status filter, derived from the backend vocabulary.
 *
 * The list comes from the generated client, so a status the backend adds shows
 * up here without a hand edit. Statuses that read the same on screen (Pending,
 * Running) share one option and are filtered on together — except the ones
 * waiting on a person: the list reads them all as "Needs action", but the
 * filter keeps input, approval, continuation and blocked apart so each can be
 * found on its own. Every status lands in exactly one option, so none becomes
 * unfindable.
 */

import type { GetAllTasksV1TasksGetData } from "@/api/client";
import { zGetAllTasksV1TasksGetQuery } from "@/api/client/zod.gen";
import { getTaskStatusPresentation, type StatusKind } from "./status";

export type TaskStatusValue = NonNullable<
  NonNullable<GetAllTasksV1TasksGetData["query"]>["status"]
>[number];

export const TASK_STATUS_VALUES: readonly TaskStatusValue[] =
  zGetAllTasksV1TasksGetQuery.shape.status.unwrap().unwrap().element.options;

/** Where an option sits in the menu: in flight, waiting on a person, over. */
export type TaskStatusFilterGroup = "active" | "attention" | "finished";

export const TASK_STATUS_FILTER_GROUPS: readonly TaskStatusFilterGroup[] = [
  "active",
  "attention",
  "finished",
];

export interface TaskStatusFilterOption {
  /** The status that names the option in the URL and renders its marker. */
  value: TaskStatusValue;
  statuses: TaskStatusValue[];
  /** Key under `TasksPage.status` naming the option, when there is one. */
  labelKey?: string;
  /** Untranslated name, for a status the presentation does not know. */
  label: string;
  group: TaskStatusFilterGroup;
}

// Each status that waits on a person gets its own option and name.
const ATTENTION_LABEL_KEYS: Partial<Record<TaskStatusValue, string>> = {
  waiting_for_input: "inputRequired",
  waiting_for_approval: "approvalRequired",
  waiting_for_continuation: "continuationRequired",
  blocked: "blocked",
};

function groupOf(kind: StatusKind): TaskStatusFilterGroup {
  if (kind === "attention") return "attention";
  if (kind === "done" || kind === "failed" || kind === "cancelled") {
    return "finished";
  }
  return "active";
}

export const TASK_STATUS_FILTER_OPTIONS: readonly TaskStatusFilterOption[] =
  (() => {
    const options = new Map<string, TaskStatusFilterOption>();
    for (const status of TASK_STATUS_VALUES) {
      const presentation = getTaskStatusPresentation(status);
      const labelKey = ATTENTION_LABEL_KEYS[status] ?? presentation.labelKey;
      const key = labelKey ?? presentation.label;
      const existing = options.get(key);
      if (existing) {
        existing.statuses.push(status);
        // The status named like the option is the one the URL carries.
        if (status === key) existing.value = status;
        continue;
      }
      options.set(key, {
        value: status,
        statuses: [status],
        labelKey,
        label: presentation.label,
        group: groupOf(presentation.kind),
      });
    }
    return [...options.values()];
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
