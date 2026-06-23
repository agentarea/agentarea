"use server";

import {
  getBillingOverview,
  listAgents,
  listMCPServerInstances,
  listOpenAPIConnections,
} from "@/lib/api";
import { getDashboard } from "@/lib/api-dashboard";

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

export interface CloudSetupEstimate {
  agent_count: number | null;
  connection_count: number | null;
  task_runs_mtd: number | null;
  agent_spend_mtd_usd: number | null;
  agent_projected_eom_usd: number | null;
  cpu_core_hours_mtd: number | null;
  memory_gb_hours_mtd: number | null;
  infra_estimate_mtd_usd: number | null;
  platform_fee_usd: number;
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

function getCollectionCount(value: unknown): number | null {
  if (Array.isArray(value)) {
    return value.length;
  }

  if (value && typeof value === "object") {
    const items = (value as { items?: unknown }).items;
    if (Array.isArray(items)) {
      return items.length;
    }
  }

  return null;
}

export async function fetchCloudSetupEstimate(): Promise<CloudSetupEstimate> {
  const [agentsResult, mcpInstancesResult, openApiResult, dashboard] =
    await Promise.all([
      listAgents().catch(() => ({ data: null })),
      listMCPServerInstances().catch(() => ({ data: null })),
      listOpenAPIConnections().catch(() => ({ data: null })),
      getDashboard().catch(() => null),
    ]);

  const mcpConnections = getCollectionCount(mcpInstancesResult.data);
  const openApiConnections = getCollectionCount(openApiResult.data);
  const knownConnectionCounts = [mcpConnections, openApiConnections].filter(
    (count): count is number => typeof count === "number"
  );

  const taskRuns =
    dashboard?.daily_tasks.reduce(
      (total, day) => total + day.completed + day.failed + day.input_required,
      0
    ) ?? null;

  return {
    agent_count: getCollectionCount(agentsResult.data),
    connection_count:
      knownConnectionCounts.length > 0
        ? knownConnectionCounts.reduce((total, count) => total + count, 0)
        : null,
    task_runs_mtd: taskRuns,
    agent_spend_mtd_usd: dashboard?.spend.mtd_usd ?? null,
    agent_projected_eom_usd: dashboard?.spend.projected_eom_usd ?? null,
    cpu_core_hours_mtd: null,
    memory_gb_hours_mtd: null,
    infra_estimate_mtd_usd: null,
    platform_fee_usd: 0,
  };
}
