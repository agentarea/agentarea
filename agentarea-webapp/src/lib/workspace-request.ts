import { getAuthToken } from "@/lib/getAuthToken";
import { getActiveWorkspaceSlug } from "@/lib/workspace-context";
import {
  WORKSPACE_REFERENCE_HEADER,
  WORKSPACE_SLUG_HEADER,
} from "@/lib/workspaces";

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
  return (
    request.headers.get(WORKSPACE_REFERENCE_HEADER) ??
    request.headers.get(WORKSPACE_SLUG_HEADER) ??
    getActiveWorkspaceSlug()
  );
}

/**
 * Headers a hand-rolled `fetch` inside a server action must carry.
 *
 * The generated client stamps the slug on every request it makes; a raw fetch
 * (multipart upload, bare DELETE) does not go through it, and without the
 * header the backend resolves the call against the user's personal workspace
 * while the listing beside it shows the switched-into one.
 */
export async function workspaceSlugHeaders(): Promise<Record<string, string>> {
  const slug = await getActiveWorkspaceSlug();
  return slug ? { [WORKSPACE_REFERENCE_HEADER]: slug } : {};
}

/**
 * Call the API from a server action without going through the generated
 * client, and still land in the workspace the user is looking at.
 *
 * Remembering the two headers per call site is what failed: an OAuth connect
 * assembled its own request, reached the backend with no slug, and 404'd on
 * the very instance the page had just rendered. Callers pass a URL and get
 * the session token and the active slug attached; an explicitly supplied
 * header still wins, and the body's content type is left alone so multipart
 * uploads keep their boundary.
 */
export async function workspaceFetch(
  url: string,
  init: RequestInit = {}
): Promise<Response> {
  const headers = new Headers(init.headers);

  const token = await getAuthToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  for (const [name, value] of Object.entries(await workspaceSlugHeaders())) {
    if (!headers.has(name)) {
      headers.set(name, value);
    }
  }

  return fetch(url, { ...init, headers });
}
