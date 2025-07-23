#!/usr/bin/env python3
"""Simple test script to verify SSE streaming works."""

import asyncio
import json
from uuid import uuid4

import httpx

async def test_sse_streaming():
    """Test SSE streaming endpoint for task events."""
    print("Testing SSE streaming...")
    
    # Test endpoint (assumes local server running on port 8000)
    base_url = "http://localhost:8000"
    agent_id = "550e8400-e29b-41d4-a716-446655440000"  # Example agent ID
    task_id = str(uuid4())
    
    url = f"{base_url}/api/v1/agents/{agent_id}/tasks/{task_id}/events/stream"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            print(f"Connecting to: {url}")
            
            async with client.stream("GET", url) as response:
                print(f"Response status: {response.status_code}")
                print("Headers:", dict(response.headers))
                
                if response.status_code != 200:
                    print(f"Error: {await response.aread()}")
                    return
                
                print("Connected to SSE stream. Listening for events...")
                
                event_count = 0
                async for chunk in response.aiter_text():
                    if chunk.strip():
                        print(f"Received chunk: {chunk.strip()}")
                        
                        # Parse SSE format
                        if chunk.startswith("event:"):
                            event_type = chunk.split(":", 1)[1].strip()
                            print(f"Event type: {event_type}")
                        elif chunk.startswith("data:"):
                            data = chunk.split(":", 1)[1].strip()
                            try:
                                parsed_data = json.loads(data)
                                print(f"Event data: {parsed_data}")
                            except json.JSONDecodeError:
                                print(f"Raw data: {data}")
                        
                        event_count += 1
                        if event_count > 10:  # Stop after 10 events for testing
                            break
                
                print(f"Received {event_count} events")
                
    except Exception as e:
        print(f"Error testing SSE: {e}")

if __name__ == "__main__":
    asyncio.run(test_sse_streaming())