import { NextRequest, NextResponse } from 'next/server';

export async function GET(
  request: NextRequest,
  { params }: { params: { taskId: string } }
) {
  try {
    const { taskId } = params;
    
    // Proxy to our backend API server running on port 8000  
    // Our backend uses /v1/chat/messages/{taskId}/status format
    const response = await fetch(`http://localhost:8000/v1/chat/messages/${taskId}/status`);
    
    if (!response.ok) {
      throw new Error(`Backend responded with status: ${response.status}`);
    }
    
    const data = await response.json();
    
    // Transform the response to match what the frontend expects
    // Backend returns: { status, content, task_id, execution_id, timestamp, error }
    if (data.status === 'completed') {
      return NextResponse.json({
        status: 'completed',
        content: data.content,
        timestamp: data.timestamp,
        task_id: data.task_id,
        execution_id: data.execution_id,
      });
    } else if (data.status === 'processing') {
      return NextResponse.json({
        status: 'processing',
        content: data.content || 'Processing...',
        task_id: data.task_id,
      });
    } else if (data.status === 'failed') {
      return NextResponse.json({
        status: 'failed',
        error: data.error || 'Task failed',
        content: data.content || 'Sorry, there was an error processing your request.',
        task_id: data.task_id,
      });
    } else {
      // Pass through the raw response for any other status
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