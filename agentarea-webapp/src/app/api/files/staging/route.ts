import { NextRequest } from "next/server";
import { env } from "@/env";
import { getAuthToken } from "@/lib/getAuthToken";

// Stage a single file for a not-yet-created task. The task-create body then
// references the returned `ref`. Auth + active-workspace forwarding mirror the
// task-create proxy so the staged file lands in the same workspace.
export async function POST(request: NextRequest) {
  try {
    const token = await getAuthToken();

    const backendHeaders: Record<string, string> = {};
    if (token) {
      backendHeaders["Authorization"] = `Bearer ${token}`;
    }

    let workspaceSlug = request.headers.get("x-workspace-slug");
    if (!workspaceSlug) {
      const referer = request.headers.get("referer");
      const match = referer?.match(/\/w\/([^/?#]+)/);
      if (match) workspaceSlug = decodeURIComponent(match[1]);
    }
    if (workspaceSlug) {
      backendHeaders["X-Workspace-Slug"] = workspaceSlug;
    }

    // Forward the multipart body (the file stream) unchanged; let the backend
    // read the `file` field. Do not set Content-Type — it carries the boundary.
    const stagingUrl = `${env.API_URL}/v1/files/staging`;
    const response = await fetch(stagingUrl, {
      method: "POST",
      headers: backendHeaders,
      body: request.body,
      duplex: "half",
    } as RequestInit & { duplex: "half" });

    return new Response(await response.text(), {
      status: response.status,
      headers: {
        "Content-Type":
          response.headers.get("content-type") || "application/json",
      },
    });
  } catch (error) {
    console.error("Staging upload proxy error:", error);
    return new Response(`Staging upload proxy error: ${error}`, { status: 500 });
  }
}
