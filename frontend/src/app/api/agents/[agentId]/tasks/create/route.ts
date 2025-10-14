import { NextRequest } from 'next/server';
import { env } from "@/env";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ agentId: string }> }
) {
  const { agentId } = await params;

  try {
    // Get auth token from the request
    const authHeader = request.headers.get('authorization');

    // Get token from auth API if not provided
    let token = authHeader?.replace('Bearer ', '');
    if (!token) {
      try {
        const tokenResponse = await fetch(`${request.nextUrl.origin}/api/auth/token`, {
          headers: {
            'cookie': request.headers.get('cookie') || ''
          }
        });
        if (tokenResponse.ok) {
          const tokenData = await tokenResponse.json();
          token = tokenData.token;
        }
      } catch (error) {
        console.error('Failed to get auth token:', error);
      }
    }

    // Get the task creation data from request body
    const taskData = await request.json();

    // Create headers for backend request
    // Note: workspace_id is already in the JWT token claims, no need to send separately
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
