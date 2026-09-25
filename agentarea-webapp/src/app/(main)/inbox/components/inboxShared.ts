import type { useFormatter } from "next-intl";
import type { TaskWithAgent } from "@/lib/api";

export const FILTER_KEYS = ["all", "pending", "completed", "failed"] as const;
export type FilterValue = (typeof FILTER_KEYS)[number];
export type InboxCounts = Record<FilterValue, number>;
export type InboxTask = TaskWithAgent & {
  total_cost?: number | null;
};

export function isPending(status: string): boolean {
  return status === "waiting_for_approval" || status === "pending";
}

export function normalizeStatus(
  status: string
): "pending" | "completed" | "failed" {
  if (isPending(status)) return "pending";
  if (status === "completed" || status === "success") return "completed";
  return "failed";
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
  if (!dateStr) return "";
  const date = new Date(dateStr);
  return Number.isNaN(date.getTime()) ? "" : format.relativeTime(date, now);
}

export function fmtCost(cost?: number | null): string {
  return cost == null ? "—" : `$${Number(cost).toFixed(4)}`;
}
