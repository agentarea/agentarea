import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    // Get the request body
    const body = await request.json();
    
    // Proxy to our backend API server running on port 8000
    const response = await fetch('http://localhost:8000/v1/chat/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    
    if (!response.ok) {
      throw new Error(`Backend responded with status: ${response.status}`);
    }
    
    const data = await response.json();
    return NextResponse.json(data);
    
  } catch (error) {
    console.error('Error proxying message to backend:', error);
    return NextResponse.json(
      { error: 'Failed to send message to backend' },
      { status: 500 }
    );
  }
} 