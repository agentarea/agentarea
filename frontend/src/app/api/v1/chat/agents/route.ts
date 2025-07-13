import { NextRequest, NextResponse } from 'next/server';

export async function GET() {
  try {
    // Proxy to our backend API server running on port 8000
    const response = await fetch('http://localhost:8000/v1/chat/agents');
    
    if (!response.ok) {
      throw new Error(`Backend responded with status: ${response.status}`);
    }
    
    const data = await response.json();
    
    // Return the agents array (the frontend expects an array, not {success: true, agents: [...]}
    return NextResponse.json(data.agents || data);
    
  } catch (error) {
    console.error('Error proxying to backend:', error);
    return NextResponse.json(
      { error: 'Failed to load agents from backend' },
      { status: 500 }
    );
  }
} 