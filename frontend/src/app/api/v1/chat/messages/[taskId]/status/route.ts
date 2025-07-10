import { NextRequest, NextResponse } from 'next/server';

export async function GET(
  request: NextRequest,
  { params }: { params: { taskId: string } }
) {
  try {
    const { taskId } = params;
    
    // Proxy to our mock API server running on port 8000  
    // Our mock server uses /api/v1/chat/tasks/{taskId} format
    const response = await fetch(`http://localhost:8000/api/v1/chat/tasks/${taskId}`);
    
    if (!response.ok) {
      throw new Error(`Backend responded with status: ${response.status}`);
    }
    
    const data = await response.json();
    
    // Transform the response to match what the frontend expects
    if (data.status === 'completed' && data.result) {
      return NextResponse.json({
        status: 'completed',
        content: data.result.response,
        timestamp: new Date().toISOString(),
      });
    } else if (data.status === 'processing') {
      return NextResponse.json({
        status: 'processing',
      });
    } else if (data.status === 'failed') {
      return NextResponse.json({
        status: 'failed',
        error: data.error || 'Task failed',
      });
    } else {
      return NextResponse.json(data);
    }
    
  } catch (error) {
    console.error('Error checking task status:', error);
    return NextResponse.json(
      { 
        status: 'failed',
        error: 'Failed to check task status' 
      },
      { status: 500 }
    );
  }
} 