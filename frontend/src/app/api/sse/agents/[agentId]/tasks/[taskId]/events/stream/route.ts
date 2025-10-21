import { NextRequest } from 'next/server';
import { env } from "@/env";
import { getAuthToken } from "@/lib/getAuthToken";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ agentId: string, taskId: string }> }
) {
  const { agentId, taskId } = await params;

  try {
    // Use session-based token retrieval only; do not handle workspace
    const token = await getAuthToken();

    // Forward native SSE stream from backend
    const backendUrl = env.API_URL;
    const eventsUrl = `${backendUrl}/v1/agents/${agentId}/tasks/${taskId}/events/stream/`;

    // Create headers for backend request
    const headers: Record<string, string> = {
      'Accept': 'text/event-stream',
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(eventsUrl, {
      method: 'GET',
      headers,
    });

    if (!response.ok) {
      return new Response(`Backend SSE error: ${response.status}`, { status: response.status });
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
            console.error('SSE events stream error:', error);
            controller.error(error);
          }
        };

        pump();
      },
    });

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
    console.error('SSE events proxy error:', error);
    return new Response(`SSE events proxy error: ${error}`, { status: 500 });
  }
}