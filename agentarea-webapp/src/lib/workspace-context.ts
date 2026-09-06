import { cache } from "react";
import { env } from "@/env";
import { SERVER_API_TIMEOUT_MS } from "@/lib/server-timeouts";
import {
  resolveActiveWorkspace,
  WORKSPACE_SLUG_COOKIE,
  type Workspace,
} from "@/lib/workspaces";

// next/headers and the session helper are imported lazily. The generated API
// client pulls this module's caller into the browser bundle, and Turbopack
// traces static server-only imports through it even when they are unreachable
// at runtime.
const serverCookies = async () => (await import("next/headers")).cookies();
const serverAuthToken = async () =>
  (await import("@/lib/getAuthToken")).getAuthToken();

export interface WorkspaceContext {
  workspaces: Workspace[];
  active: Workspace | null;
}

const EMPTY: WorkspaceContext = { workspaces: [], active: null };

/**
 * Fetch the caller's workspaces without going through the generated client.
 *
 * The client wrapper stamps X-AgentArea-Workspace on every request, and the backend
 * 403s a slug the caller is not a member of — including on this endpoint. A
 * cookie left over from a workspace the user was removed from would therefore
 * break the one call needed to recover from it. Listing is user-scoped anyway,
 * so it deliberately carries no workspace header.
 */
async function fetchWorkspaces(): Promise<Workspace[]> {
  const token = await serverAuthToken();
  if (!token) return [];

  const response = await fetch(`${env.API_URL}/v1/workspaces`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    signal: AbortSignal.timeout(SERVER_API_TIMEOUT_MS),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`GET /v1/workspaces responded ${response.status}`);
  }
  return (await response.json()) as Workspace[];
}

async function getWorkspaceContextImpl(): Promise<WorkspaceContext> {
  try {
    const cookieStore = await serverCookies();
    const workspaces = await fetchWorkspaces();
    return {
      workspaces,
      active: resolveActiveWorkspace(
        workspaces,
        cookieStore.get(WORKSPACE_SLUG_COOKIE)?.value
      ),
    };
  } catch (error) {
    // The switcher is chrome, not content: an API outage must not take the
    // whole app shell down with it.
    console.error("[workspace-context] failed to list workspaces:", error);
    return EMPTY;
  }
}

export const getWorkspaceContext = cache(getWorkspaceContextImpl);

/**
 * The slug every outgoing request should be scoped to, or null for the
 * backend's own default. Resolved rather than read straight from the cookie so
 * a stale value degrades to the personal workspace instead of 403-ing the app.
 */
export async function getActiveWorkspaceSlug(): Promise<string | null> {
  const { active } = await getWorkspaceContext();
  return active?.slug ?? null;
}
