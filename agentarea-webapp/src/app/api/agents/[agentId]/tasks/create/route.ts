import { NextRequest } from "next/server";
import { env } from "@/env";
import { getAuthToken } from "@/lib/getAuthToken";
import { resolveRequestWorkspaceSlug } from "@/lib/workspace-request";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ agentId: string }> }
) {
  const { agentId } = await params;

  try {
    // Keep credentials server-side while forwarding the active workspace slug.
    const token = await getAuthToken();

    // Create headers for backend request
    const backendHeaders: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };

    if (token) {
      backendHeaders["Authorization"] = `Bearer ${token}`;
    }

    const workspaceSlug = await resolveRequestWorkspaceSlug(request);
    if (workspaceSlug) {
      backendHeaders["X-Workspace-Slug"] = workspaceSlug;
    }

    // Task creation is JSON. Files are pre-staged via POST /v1/files/upload-url
    // (presigned upload) and referenced by ref in the body's `attachments` array.
    const backendUrl = env.API_URL;
    const createTaskUrl = `${backendUrl}/v1/agents/${agentId}/tasks/`;

    const response = await fetch(createTaskUrl, {
      method: "POST",
      headers: backendHeaders,
      body: await request.text(),
    });

    if (!response.ok) {
      return new Response(await response.text(), {
        status: response.status,
        headers: {
          "Content-Type":
            response.headers.get("content-type") || "text/plain; charset=utf-8",
        },
      });
    }

    // Create a readable stream that forwards the SSE data
    const stream = new ReadableStream({
      start(controller) {
        const reader = response.body?.getReader();
        if (!reader) {
          controller.close();
          return;
        }

        const pump = async () => {
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) {
                controller.close();
                break;
              }
              controller.enqueue(value);
            }
          } catch (error) {
            console.error("Task creation SSE stream error:", error);
            controller.error(error);
          }
        };

        pump();
      },
    });

    // Return SSE response with proper headers
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Cache-Control",
      },
    });
  } catch (error) {
    console.error("Task creation proxy error:", error);
    return new Response(`Task creation proxy error: ${error}`, { status: 500 });
  }
}
