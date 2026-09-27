import { cache } from "react";
import { listWorkspacesV1WorkspacesGet } from "@/api/client/sdk.gen";
import { workspacePath } from "@/lib/workspace-routes";
import {
  personalWorkspace,
  WORKSPACE_REFERENCE_HEADER,
  type Workspace,
} from "@/lib/workspaces";

// next/headers and the session helper are imported lazily. The generated API
// client pulls this module's caller into the browser bundle, and Turbopack
// traces static server-only imports through it even when they are unreachable
// at runtime.
const serverHeaders = async () => (await import("next/headers")).headers();
const serverAuthToken = async () =>
  (await import("@/lib/getAuthToken")).getAuthToken();

export interface WorkspaceContext {
  workspaces: Workspace[];
  active: Workspace | null;
}

const EMPTY: WorkspaceContext = { workspaces: [], active: null };

/**
 * Fetch the caller's workspaces. Listing is user-scoped: `/v1/workspaces`
 * has no workspace in its path, so a `/w/{slug}` URL for a workspace the user
 * was removed from cannot break the one call needed to 404 it.
 */
async function fetchWorkspaces(): Promise<Workspace[]> {
  const token = await serverAuthToken();
  if (!token) return [];

  const { data, error, response } = await listWorkspacesV1WorkspacesGet({
    cache: "no-store",
  });
  if (error || !data) {
    throw new Error(`GET /v1/workspaces responded ${response?.status}`);
  }
  return data;
}

/** The caller's workspaces; throws when the API cannot list them. */
export const getWorkspaces = cache(fetchWorkspaces);

/**
 * The workspace of the page this request renders or posts to — the one place
 * server code reads it. The proxy sets the header from the `/w/{slug}` URL and
 * overwrites any client value; in a route handler it is what the browser sent.
 */
export async function getRequestWorkspaceSlug(): Promise<string | null> {
  return (await serverHeaders()).get(WORKSPACE_REFERENCE_HEADER);
}

async function getWorkspaceContextImpl(): Promise<WorkspaceContext> {
  try {
    const [workspaces, slug] = await Promise.all([
      getWorkspaces(),
      getRequestWorkspaceSlug(),
    ]);
    return {
      workspaces,
      active: workspaces.find((workspace) => workspace.slug === slug) ?? null,
    };
  } catch (error) {
    // The switcher is chrome, not content: an API outage must not take the
    // whole app shell down with it.
    console.error("[workspace-context] failed to list workspaces:", error);
    return EMPTY;
  }
}

export const getWorkspaceContext = cache(getWorkspaceContextImpl);

export interface ViewerCapabilities {
  canAdminister: boolean;
}

/**
 * What the caller may do in the workspace of this request, as the API decided
 * it. Throws when the request names no workspace the caller belongs to.
 */
async function getViewerCapabilitiesImpl(): Promise<ViewerCapabilities> {
  const [workspaces, slug] = await Promise.all([
    getWorkspaces(),
    getRequestWorkspaceSlug(),
  ]);
  const active = workspaces.find((workspace) => workspace.slug === slug);
  if (!active) {
    throw new Error(
      `No workspace of the caller matches the request workspace "${slug}"`
    );
  }
  return { canAdminister: active.can_administer };
}

export const getViewerCapabilities = cache(getViewerCapabilitiesImpl);

/**
 * `path` inside the caller's personal workspace: where `/`, a fresh sign-in
 * and links from outside any workspace (invitations, Ory settings) land.
 */
export async function getPersonalWorkspacePath(path: string): Promise<string> {
  const personal = personalWorkspace(await getWorkspaces());
  if (!personal) {
    throw new Error("The caller has no personal workspace to land in");
  }
  return workspacePath(personal.slug, path);
}
