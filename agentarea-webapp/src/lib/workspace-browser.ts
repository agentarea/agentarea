import { workspaceSlugFromPath } from "@/lib/workspace-routes";
import { WORKSPACE_REFERENCE_HEADER } from "@/lib/workspaces";

/**
 * The workspace of the `/w/{slug}` page the browser is on, for code outside
 * React; components use `useWorkspaceSlug()`.
 */
export function currentWorkspaceSlug(): string | null {
  if (typeof window === "undefined") return null;
  return workspaceSlugFromPath(window.location.pathname);
}

/** The header a browser call to an /api route handler carries. */
export function currentWorkspaceHeaders(): Record<string, string> {
  const slug = currentWorkspaceSlug();
  return slug ? { [WORKSPACE_REFERENCE_HEADER]: slug } : {};
}
