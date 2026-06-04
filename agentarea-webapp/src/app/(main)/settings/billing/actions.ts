"use server";

import { getBillingOverview } from "@/lib/api";

export type BillingPlanKey = "free" | "payg" | "enterprise";

export type BillingStatus =
  | "active"
  | "trialing"
  | "past_due"
  | "canceled"
  | string;

export interface BillingSubscription {
  /** Plan the workspace is currently on. */
  plan: BillingPlanKey;
  /** Subscription lifecycle state. */
  status: BillingStatus;
  /** ISO timestamp the current period ends, or null for plans without a period. */
  current_period_end?: string | null;
}

export interface BillingUsageItem {
  /** Stable metric key (workspaces, agents, mcp_connections, task_runs, ...). */
  key: string;
  /** Amount consumed in the current period. */
  used: number;
  /** Allowance for the period; null means unlimited. */
  limit: number | null;
}

export interface BillingOverview {
  subscription: BillingSubscription | null;
  usage: BillingUsageItem[];
}

export interface BillingOverviewResult {
  data: BillingOverview | null;
  /** True when the billing service answered; false when it is not deployed (404). */
  available: boolean;
  error: string | null;
}

/**
 * Fetches billing state from the expected `/v1/billing/overview` endpoint.
 *
 * Billing lives in the enterprise/billing service, so on a core deployment the
 * endpoint does not exist. A 404 is treated as "not available" (clean empty
 * state) rather than an error — we never invent plan or usage numbers.
 */
export async function fetchBillingOverview(): Promise<BillingOverviewResult> {
  const { data, error, status } = await getBillingOverview();

  if (status === 404) {
    return { data: null, available: false, error: null };
  }

  if (error || !data) {
    return {
      data: null,
      available: true,
      error: "Failed to load billing information",
    };
  }

  return {
    data: data as unknown as BillingOverview,
    available: true,
    error: null,
  };
}
