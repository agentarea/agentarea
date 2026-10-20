import { NextRequest } from "next/server";
import { env } from "@/env";
import { formatApiError } from "@/lib/api-errors";
import { getAuthToken } from "@/lib/getAuthToken";
import { resolveRequestWorkspaceSlug } from "@/lib/workspace-request";
import { fillWorkspace } from "@/lib/workspace-url";
import { WORKSPACE_QUERY_PARAM } from "@/lib/workspaces";

/** The workspace events feed's live tail, forwarded from the backend as it comes. */
export async function GET(request: NextRequest) {
  try {
    const token = await getAuthToken();
    const query = new URLSearchParams(request.nextUrl.searchParams);
    query.delete(WORKSPACE_QUERY_PARAM);
    const search = query.toString();
    const liveUrl = fillWorkspace(
      `${env.AGENTAREA_API_URL}/v1/workspaces/{workspace}/streams/events/live${search ? `?${search}` : ""}`,
      resolveRequestWorkspaceSlug(request)
    );
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const response = await fetch(liveUrl, {
      method: "GET",
      headers,
      signal: request.signal,
    });
    if (!response.ok || !response.body) {
      return new Response(`Backend SSE error: ${response.status}`, {
        status: response.status || 502,
      });
    }
    return new Response(response.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  } catch (error) {
    console.error("Events live proxy error:", error);
    return new Response(`Events live proxy error: ${formatApiError(error)}`, {
      status: 500,
    });
  }
}
