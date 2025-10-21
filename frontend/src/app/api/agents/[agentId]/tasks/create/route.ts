import { NextRequest } from 'next/server';
import { env } from "@/env";
import { getAuthToken } from "@/lib/getAuthToken";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ agentId: string }> }
) {
  const { agentId } = await params;

  try {
    // Use session-based token retrieval only; do not handle workspace
    const token = await getAuthToken();

    // Get the task creation data from request body
    const taskData = await request.json();

    // Create headers for backend request
    const backendHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
    };

    if (token) {
      backendHeaders['Authorization'] = `Bearer ${token}`;
    }

    // Connect to backend task creation endpoint with SSE (server-side only)
    const backendUrl = env.API_URL;
    const createTaskUrl = `${backendUrl}/v1/agents/${agentId}/tasks/`;

    const response = await fetch(createTaskUrl, {
      method: 'POST',
      headers: backendHeaders,
      body: JSON.stringify(taskData),
    });

    if (!response.ok) {
      return new Response(`Backend task creation error: ${response.status}`, {
        status: response.status
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
            console.error('Task creation SSE stream error:', error);
            controller.error(error);
          }
        };

        pump();
      },
    });

    // Return SSE response with proper headers
    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Cache-Control',
      },
    });

  } catch (error) {
    console.error('Task creation proxy error:', error);
    return new Response(`Task creation proxy error: ${error}`, { status: 500 });
  }
}
