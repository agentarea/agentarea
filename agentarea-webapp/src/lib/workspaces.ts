// Carries the page's workspace inside the webapp: from the proxy to server
// code, and from the browser to /api route handlers. Never sent to the API,
// which takes the workspace from its `/v1/workspaces/{workspace}` path.
export const WORKSPACE_REFERENCE_HEADER = "x-agentarea-workspace";
// For browser requests that cannot carry a header: EventSource, <a download>.
export const WORKSPACE_QUERY_PARAM = "workspace";

export type Workspace = {
  id: string;
  slug: string;
  name: string;
  owner_user_id: string;
};

/**
 * A workspace auto-provisioned for a single user, recognised by its id being
 * that user's own id.
 *
 * Derived rather than read from a ``type`` field: the backend used to store
 * that alongside the id it described, which is one copy too many. Owning a
 * workspace is not the same thing — you own every workspace you create.
 */
export function isPersonalWorkspace(workspace: Workspace): boolean {
  return workspace.id === workspace.owner_user_id;
}

/** The workspace `/` and a fresh sign-in land in. */
export function personalWorkspace<T extends Workspace>(
  workspaces: T[]
): T | null {
  return workspaces.find(isPersonalWorkspace) ?? null;
}

/** Append the workspace to a same-origin API URL as a query parameter. */
export function withWorkspaceQuery(url: string, slug: string | null): string {
  if (!slug) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}${WORKSPACE_QUERY_PARAM}=${encodeURIComponent(slug)}`;
}
