// Dashboard-specific fetcher for server-only callers.

import "server-only";
import { env } from "@/env";
import { getAuthToken } from "./getAuthToken";
import { workspaceSlugHeaders } from "./workspace-request";

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

  for (const [name, value] of Object.entries(await workspaceSlugHeaders())) {
    if (!headers.has(name)) {
      headers.set(name, value);
    }
  }

  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${env.API_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}

export async function getDashboard(): Promise<DashboardData> {
  const res = await authedFetch("/v1/workspace/dashboard");
  if (!res.ok) {
    throw new Error(`Dashboard fetch failed: ${res.status}`);
  }
  return res.json();
}

export async function getWorkspaceSettings(): Promise<WorkspaceSettings> {
  const res = await authedFetch("/v1/workspace/settings");
  if (!res.ok) {
    throw new Error(`Workspace settings fetch failed: ${res.status}`);
  }
  return res.json();
}

export async function getAgentOverview(
  agentId: string
): Promise<AgentOverviewData> {
  const res = await authedFetch(
    `/v1/agents/${encodeURIComponent(agentId)}/overview`
  );
  if (!res.ok) {
    throw new Error(`Agent overview fetch failed: ${res.status}`);
  }
  return res.json();
}

export async function updateWorkspaceSettings(
  monthly_cap_usd: number | null
): Promise<WorkspaceSettings> {
  const res = await authedFetch("/v1/workspace/settings", {
    method: "PUT",
    body: JSON.stringify({ monthly_cap_usd }),
  });
  if (!res.ok) {
    throw new Error(`Workspace settings update failed: ${res.status}`);
  }
  return res.json();
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
