import { getAuthToken } from "@/lib/getAuthToken";
import { getRequestWorkspaceSlug } from "@/lib/workspace-context";
import { workspacePath } from "@/lib/workspace-routes";
import { fillWorkspace } from "@/lib/workspace-url";
import {
  WORKSPACE_QUERY_PARAM,
  WORKSPACE_REFERENCE_HEADER,
} from "@/lib/workspaces";

/**
 * The workspace a browser call to a route handler names.
 *
 * Route handlers sit outside the proxy, so the browser sends the slug of the
 * page it is on: as a header, or as a query parameter where it cannot set one
 * (EventSource, download links). Transport only — the backend authorizes
 * membership.
 */
export function resolveRequestWorkspaceSlug(request: Request): string | null {
  return (
    request.headers.get(WORKSPACE_REFERENCE_HEADER) ??
    new URL(request.url).searchParams.get(WORKSPACE_QUERY_PARAM)
  );
}

/**
 * `path` inside the workspace of the page a server action or component runs
 * for. Throws off a workspace page: there is no workspace to send them to.
 */
export async function requestWorkspacePath(path: string): Promise<string> {
  const slug = await getRequestWorkspaceSlug();
  if (!slug) {
    throw new Error(`No workspace in the request to scope ${path} to`);
  }
  return workspacePath(slug, path);
}

/**
 * Call the API from a server action without going through the generated
 * client, and still land in the workspace the user is looking at.
 *
 * Callers pass a `/v1/workspaces/{workspace}/...` URL and get the session
 * token attached and the page's slug filled in; a workspace-less URL goes out
 * unchanged. An explicitly supplied Authorization header still wins, and the
 * body's content type is left alone so multipart uploads keep their boundary.
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

  return fetch(fillWorkspace(url, await getRequestWorkspaceSlug()), {
    ...init,
    headers,
  });
}
