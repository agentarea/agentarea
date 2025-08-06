import { NextRequest } from 'next/server';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ agentId: string; taskId: string }> }
) {
  const { agentId, taskId } = await params;
  
  try {
    // Get auth token from the request
    const authHeader = request.headers.get('authorization');
    const workspaceHeader = request.headers.get('x-workspace-id') || 'default';
    
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

    // Create headers for backend request
    const backendHeaders: Record<string, string> = {
      'Accept': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'X-Workspace-ID': workspaceHeader,
    };

    if (token) {
      backendHeaders['Authorization'] = `Bearer ${token}`;
    }

    // Connect to backend SSE endpoint
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const sseUrl = `${backendUrl}/v1/agents/${agentId}/tasks/${taskId}/events/stream`;
    
    const response = await fetch(sseUrl, {
      headers: backendHeaders,
    });

    if (!response.ok) {
      return new Response(`Backend SSE error: ${response.status}`, { 
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
            console.error('SSE stream error:', error);
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
    console.error('SSE proxy error:', error);
    return new Response(`SSE proxy error: ${error}`, { status: 500 });
  }
}