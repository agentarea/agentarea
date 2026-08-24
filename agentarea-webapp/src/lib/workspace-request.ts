import { getActiveWorkspaceSlug } from "@/lib/workspace-context";
import { WORKSPACE_SLUG_HEADER } from "@/lib/workspaces";

/**
 * Resolve the active workspace for a route handler.
 *
 * Route handlers are not covered by the generated client's fetch wrapper, so
 * they forward the slug themselves. An explicit header wins; otherwise the
 * switcher decides. Transport only — the backend authorizes membership.
 */
export async function resolveRequestWorkspaceSlug(
  request: Request
): Promise<string | null> {
  return request.headers.get(WORKSPACE_SLUG_HEADER) ?? getActiveWorkspaceSlug();
}
