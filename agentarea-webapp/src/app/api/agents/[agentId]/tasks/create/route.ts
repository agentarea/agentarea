import { NextRequest } from "next/server";
import { env } from "@/env";
import { formatApiError } from "@/lib/api-errors";
import { getAuthToken } from "@/lib/getAuthToken";
import { resolveRequestWorkspaceSlug } from "@/lib/workspace-request";
import { WORKSPACE_REFERENCE_HEADER } from "@/lib/workspaces";

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
      backendHeaders[WORKSPACE_REFERENCE_HEADER] = workspaceSlug;
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
    let upstreamReader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let downstreamCancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const reader = response.body?.getReader();
        if (!reader) {
          controller.close();
          return;
        }
        upstreamReader = reader;

        const pump = async () => {
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) {
                if (!downstreamCancelled) controller.close();
                break;
              }
              controller.enqueue(value);
            }
          } catch (error) {
            if (!downstreamCancelled) {
              console.error("Task creation SSE stream error:", error);
              controller.error(error);
            }
          }
        };

        pump();
      },
      async cancel(reason) {
        downstreamCancelled = true;
        await upstreamReader?.cancel(reason).catch(() => undefined);
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
    return new Response(`Task creation proxy error: ${formatApiError(error)}`, {
      status: 500,
    });
  }
}
