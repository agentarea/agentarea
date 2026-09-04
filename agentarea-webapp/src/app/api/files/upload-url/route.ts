import { NextRequest } from "next/server";
import { env } from "@/env";
import { formatApiError } from "@/lib/api-errors";
import { getAuthToken } from "@/lib/getAuthToken";
import { resolveRequestWorkspaceSlug } from "@/lib/workspace-request";

// Mint a presigned PUT for a task attachment. The client uploads the file
// bytes directly to the object store with the returned `upload_url`, then
// references the returned `ref` in the task-create body's `attachments` array.
export async function POST(request: NextRequest) {
  try {
    const token = await getAuthToken();

    const backendHeaders: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (token) {
      backendHeaders["Authorization"] = `Bearer ${token}`;
    }

    const workspaceSlug = await resolveRequestWorkspaceSlug(request);
    if (workspaceSlug) {
      backendHeaders["X-Workspace-Slug"] = workspaceSlug;
    }

    const uploadUrlEndpoint = `${env.API_URL}/v1/files/upload-url`;
    const response = await fetch(uploadUrlEndpoint, {
      method: "POST",
      headers: backendHeaders,
      body: await request.text(),
    });

    return new Response(await response.text(), {
      status: response.status,
      headers: {
        "Content-Type":
          response.headers.get("content-type") || "application/json",
      },
    });
  } catch (error) {
    console.error("Upload-url proxy error:", error);
    return new Response(`Upload-url proxy error: ${formatApiError(error)}`, {
      status: 500,
    });
  }
}
