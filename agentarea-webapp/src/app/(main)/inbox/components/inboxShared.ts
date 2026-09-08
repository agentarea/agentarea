import { formatDistanceToNowStrict } from "date-fns";
import type { TaskWithAgent } from "@/lib/api";

export const INBOX_PAGE_SIZE = 50;

export const FILTER_KEYS = ["all", "pending", "completed", "failed"] as const;
export type FilterValue = (typeof FILTER_KEYS)[number];
export type InboxCounts = Record<FilterValue, number>;
export type InboxTask = TaskWithAgent & {
  total_cost?: number | null;
};

export const FILTERS: { key: FilterValue; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pending", label: "Needs approval" },
  { key: "completed", label: "Completed" },
  { key: "failed", label: "Failed" },
];

export const STATUS_LABEL: Record<string, string> = {
  pending: "Needs approval",
  completed: "Completed",
  failed: "Failed",
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
 * Fold a backend `{status: count}` map into UI filter buckets. These totals
 * span the whole workspace, so segment counts stay accurate regardless of how
 * many pages the infinite scroll has loaded.
 */
export function bucketStatusCounts(
  statusCounts: Record<string, number> | null | undefined
): InboxCounts {
  const next: InboxCounts = { all: 0, pending: 0, completed: 0, failed: 0 };
  for (const [status, count] of Object.entries(statusCounts ?? {})) {
    next.all += count;
    next[normalizeStatus(status)] += count;
  }
  return next;
}

export function formatRelative(dateStr?: string | null): string {
  if (!dateStr) return "";
  try {
    return formatDistanceToNowStrict(new Date(dateStr), { addSuffix: true });
  } catch {
    return "";
  }
}

export function fmtCost(cost?: number | null): string {
  return cost == null ? "—" : `$${Number(cost).toFixed(4)}`;
}
