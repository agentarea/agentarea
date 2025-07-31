#!/usr/bin/env python3
"""
Test task creation with proper SSE handling.
"""

import asyncio
import json
import logging
from datetime import datetime
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE_URL = "http://localhost:8000"

async def test_sse_task_creation():
    """Test task creation with proper SSE stream handling."""
    
    logger.info("🚀 Testing SSE task creation...")
    
    # Step 1: Get an existing agent
    async with httpx.AsyncClient() as client:
        agents_response = await client.get(f"{API_BASE_URL}/v1/agents/")
        if agents_response.status_code == 200:
            agents = agents_response.json()
            if agents and len(agents) > 0:
                agent_id = agents[0]["id"]
                logger.info(f"✅ Using existing agent: {agent_id}")
            else:
                logger.error("❌ No existing agents found")
                return
        else:
            logger.error(f"❌ Failed to list agents: {agents_response.status_code}")
            return
    
    # Step 2: Create task with SSE stream
    task_data = {
        "description": "Test SSE task creation - please respond with 'Hello from SSE!'"
    }
    
    logger.info("📝 Creating task with SSE stream...")
    
    task_id = None
    events_received = 0
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                f"{API_BASE_URL}/v1/agents/{agent_id}/tasks/",
                json=task_data
            ) as response:
                
                if response.status_code != 200:
                    logger.error(f"❌ Failed to create task: {response.status_code}")
                    return
                
                logger.info("✅ SSE stream started successfully")
                
                async for line in response.aiter_lines():
                    if line.strip():
                        events_received += 1
                        logger.info(f"📡 Raw line {events_received}: {line}")
                        
                        # Parse SSE format
                        if line.startswith("data: "):
                            try:
                                data_str = line[6:]  # Remove "data: " prefix
                                logger.info(f"   Parsing: {data_str}")
                                data = json.loads(data_str)
                                event_type = data.get("type", "unknown")
                                event_data = data.get("data", {})
                                
                                logger.info(f"   📋 Event type: {event_type}")
                                
                                # Extract task ID from task_created event
                                if event_type == "task_created" and "task_id" in event_data:
                                    task_id = event_data["task_id"]
                                    logger.info(f"✅ Task created: {task_id}")
                                
                                # Log important events
                                if event_type in ["connected", "task_created", "task_completed", "task_failed", "error"]:
                                    logger.info(f"   📋 {event_type}: {event_data.get('message', 'No message')}")
                                
                                # Stop after terminal events or after reasonable number of events
                                if event_type in ["task_completed", "task_failed", "error"] or events_received > 10:
                                    logger.info(f"🏁 Stopping after {events_received} events")
                                    break
                                    
                            except json.JSONDecodeError as e:
                                logger.warning(f"⚠️ Failed to parse SSE data: {e}")
                                logger.warning(f"   Raw line: {line}")
                        
                        # Stop after reasonable time
                        if events_received > 20:
                            logger.info("🛑 Stopping after too many events")
                            break
                
    except Exception as e:
        logger.error(f"❌ Error during SSE stream: {e}")
        return
    
    # Step 3: Verify task was created
    if task_id:
        logger.info(f"🔍 Verifying task {task_id} was created...")
        
        async with httpx.AsyncClient() as client:
            try:
                task_response = await client.get(f"{API_BASE_URL}/v1/tasks/{task_id}")
                
                if task_response.status_code == 200:
                    task = task_response.json()
                    logger.info(f"✅ Task verified: {task['status']}")
                    logger.info(f"   Description: {task['description']}")
                    logger.info(f"   Created: {task['created_at']}")
                else:
                    logger.warning(f"⚠️ Could not verify task: {task_response.status_code}")
                    
            except Exception as e:
                logger.warning(f"⚠️ Error verifying task: {e}")
    
    # Step 4: Check worker logs for workflow execution
    logger.info("📊 Summary:")
    logger.info(f"   Events received: {events_received}")
    logger.info(f"   Task ID: {task_id}")
    logger.info("   Check worker logs for workflow execution details")
    
    return task_id is not None

if __name__ == "__main__":
    success = asyncio.run(test_sse_task_creation())
    if success:
        print("\n🎉 SSE Task creation test PASSED!")
    else:
        print("\n💥 SSE Task creation test FAILED!")
        exit(1)