import type { useFormatter } from "next-intl";
import type { GetInboxItemsV1InboxGetData } from "@/api/client";
import type { ApprovalDecision } from "@/api/client/types.gen";
import type { TaskWithAgent } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { parseUtcTimestamp } from "@/utils/dateUtils";

export const FILTER_KEYS = [
  "all",
  "pending",
  "input",
  "completed",
  "failed",
  "decided",
] as const;
export type FilterValue = (typeof FILTER_KEYS)[number];
export type InboxCounts = Record<FilterValue, number>;
export type InboxTask = TaskWithAgent & {
  total_cost?: number | null;
};
/** A recorded approval decision with its decider resolved to a name. */
export type InboxDecision = ApprovalDecision & {
  decided_by_name: string | null;
};

type InboxStatus = NonNullable<
  NonNullable<GetInboxItemsV1InboxGetData["query"]>["status"]
>;
/** Task-status buckets; "decided" lists approval decisions, not tasks. */
type InboxBucket = Exclude<FilterValue, "all" | "decided">;

const BUCKET_BY_STATUS: Record<InboxStatus, InboxBucket> = {
  waiting_for_approval: "pending",
  waiting_for_input: "input",
  completed: "completed",
  failed: "failed",
};

/** Approving or rejecting an escalation resumes the task, which leaves the inbox. */
export const RESOLVED_ESCALATION_STATUS = "running";

export function inboxBucket(status: string): InboxBucket | null {
  return Object.hasOwn(BUCKET_BY_STATUS, status)
    ? BUCKET_BY_STATUS[status as InboxStatus]
    : null;
}

export function isPending(status: string): boolean {
  return inboxBucket(status) === "pending";
}

/**
 * Counts per filter, plus the statuses no filter can hold. `decided` is the
 * number of recorded approval decisions; those are not tasks, so `all` leaves
 * them out.
 */
export function countInbox(
  statuses: string[],
  decided = 0
): {
  counts: InboxCounts;
  unknown: string[];
} {
  const counts: InboxCounts = {
    all: statuses.length,
    pending: 0,
    input: 0,
    completed: 0,
    failed: 0,
    decided,
  };
  const unknown: string[] = [];
  for (const status of statuses) {
    const bucket = inboxBucket(status);
    if (bucket) counts[bucket]++;
    else if (status !== RESOLVED_ESCALATION_STATUS) unknown.push(status);
  }
  return { counts, unknown };
}

/**
 * "2 days ago" in the active locale. Pass next-intl's `useFormatter()` and
 * `useNow()`: an explicit `now` keeps server and client markup in step.
 */
export function formatRelative(
  format: Pick<ReturnType<typeof useFormatter>, "relativeTime">,
  now: Date,
  dateStr?: string | null
): string {
  const date = parseUtcTimestamp(dateStr);
  return date ? format.relativeTime(date, now) : "";
}

export function fmtCost(
  cost?: number | null,
  currency: string | null = null,
  locale: string = "en"
): string {
  return cost == null ? "—" : formatMoney(Number(cost), currency, locale);
}
