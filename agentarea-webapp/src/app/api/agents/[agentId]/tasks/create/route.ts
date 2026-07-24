import { NextRequest } from "next/server";
import { env } from "@/env";
import { getAuthToken } from "@/lib/getAuthToken";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ agentId: string }> }
) {
  const { agentId } = await params;

  try {
    // Keep credentials server-side while forwarding the active workspace slug.
    const token = await getAuthToken();

    const incomingContentType = request.headers.get("content-type") || "";
    const isMultipart = incomingContentType
      .toLowerCase()
      .startsWith("multipart/form-data");

    // Create headers for backend request
    const backendHeaders: Record<string, string> = {
      "Content-Type": incomingContentType || "application/json",
      Accept: "text/event-stream",
    };

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

    // Connect to backend task creation endpoint with SSE (server-side only)
    const backendUrl = env.API_URL;
    const endpoint = isMultipart ? "with-attachments" : "";
    const createTaskUrl = `${backendUrl}/v1/agents/${agentId}/tasks/${endpoint}`;

    const requestInit: RequestInit & { duplex?: "half" } = {
      method: "POST",
      headers: backendHeaders,
      body: request.body,
      duplex: "half",
    };
    const response = await fetch(createTaskUrl, requestInit);

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
