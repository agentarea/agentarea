// Dashboard-specific fetcher for server-only callers.

import "server-only";
import { env } from "@/env";
import { getAuthToken } from "./getAuthToken";
import { getRequestWorkspaceSlug } from "./workspace-context";
import { fillWorkspace } from "./workspace-url";

export type DashboardSpend = {
  today_usd: number;
  mtd_usd: number;
  cap_usd: number | null;
  pct_of_cap: number | null;
  projected_eom_usd: number | null;
  projection_method: string;
};

export type DashboardHitlBlocker = {
  task_id: string;
  agent_id: string;
  agent_name: string;
  description: string;
  created_at: string;
};

export type DashboardWalletExhausted = {
  agent_id: string;
  agent_name: string;
  budget_usd: number;
  period: string;
};

export type DashboardFailedTask = {
  task_id: string;
  agent_id: string;
  agent_name: string;
  error: string | null;
  occurred_at: string;
};

export type DashboardAgentRow = {
  agent_id: string;
  name: string;
  tasks_done_today: number;
  tasks_failed_today: number;
  recent_task_names: string[];
  last_activity_at: string | null;
  cost_today_usd: number;
  cost_mtd_usd: number;
};

export type DailySpendPoint = { date: string; usd: number };
export type DailyTaskCounts = {
  date: string;
  completed: number;
  failed: number;
  input_required: number;
};

export type DashboardData = {
  spend: DashboardSpend;
  blockers: {
    hitl: DashboardHitlBlocker[];
    wallet_exhausted: DashboardWalletExhausted[];
    failed_24h: DashboardFailedTask[];
  };
  agents: DashboardAgentRow[];
  daily_spend: DailySpendPoint[];
  daily_tasks: DailyTaskCounts[];
};

export type AgentUpcomingItem = {
  fires_at: string;
  kind: "trigger" | "pending_task" | "running_task";
  title: string;
  trigger_id: string | null;
  task_id: string | null;
  cron_expression: string | null;
};

export type AgentOverviewData = {
  cost_today_usd: number;
  cost_mtd_usd: number;
  tasks_done_today: number;
  tasks_failed_today: number;
  last_activity_at: string | null;
  daily_spend: DailySpendPoint[];
  daily_tasks: DailyTaskCounts[];
  upcoming: AgentUpcomingItem[];
};

export type WorkspaceSettings = {
  monthly_cap_usd: number | null;
};

async function authedFetch(path: string, init?: RequestInit) {
  const token = await getAuthToken();
  if (!token) {
    throw new Error(`[Dashboard Client] ${path} - No auth token available`);
  }

  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);

  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const url = fillWorkspace(
    `${env.API_URL}${path}`,
    await getRequestWorkspaceSlug()
  );
  return fetch(url, {
    ...init,
    headers,
    cache: "no-store",
  });
}

export type DashboardResult<T> = {
  data?: T;
  error?: unknown;
  status: number;
};

/** A failed request keeps its status and the API's own error body. */
async function request<T>(
  path: string,
  init?: RequestInit
): Promise<DashboardResult<T>> {
  const res = await authedFetch(path, init);
  if (res.ok) return { data: (await res.json()) as T, status: res.status };

  const body = await res.text();
  let error: unknown = body || undefined;
  try {
    error = body ? JSON.parse(body) : undefined;
  } catch {
    // Not JSON: the raw text is the reason.
  }
  return { error, status: res.status };
}

export function getDashboard() {
  return request<DashboardData>("/v1/workspaces/{workspace}/dashboard");
}

export function getWorkspaceSettings() {
  return request<WorkspaceSettings>("/v1/workspaces/{workspace}/settings");
}

export function getAgentOverview(agentId: string) {
  return request<AgentOverviewData>(
    `/v1/workspaces/{workspace}/agents/${encodeURIComponent(agentId)}/overview`
  );
}

export function updateWorkspaceSettings(monthly_cap_usd: number | null) {
  return request<WorkspaceSettings>("/v1/workspaces/{workspace}/settings", {
    method: "PUT",
    body: JSON.stringify({ monthly_cap_usd }),
  });
}

/**
 * The workspace's billing currency (C2, `GET /v1/pricing/currency`). Every
 * caller of this must default to "USD" rather than surface an error — a
 * failed lookup must not block money from rendering, and mislabeling a USD
 * number as another currency would be worse than a wrong-but-plausible
 * default.
 */
export async function getPricingCurrency(): Promise<{ currency: string }> {
  try {
    const res = await authedFetch("/v1/pricing/currency");
    if (!res.ok) return { currency: "USD" };
    const data = await res.json();
    return {
      currency: typeof data?.currency === "string" ? data.currency : "USD",
    };
  } catch {
    return { currency: "USD" };
  }
}
