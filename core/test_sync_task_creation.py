#!/usr/bin/env python3
"""
Test task creation using the synchronous endpoint.
"""

import asyncio
import logging
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE_URL = "http://localhost:8000"

async def test_sync_task_creation():
    """Test task creation using the sync endpoint."""
    
    logger.info("🚀 Testing sync task creation...")
    
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
                return False
        else:
            logger.error(f"❌ Failed to list agents: {agents_response.status_code}")
            return False
    
    # Step 2: Create task using sync endpoint
    task_data = {
        "description": "Test sync task creation - please respond with 'Hello from sync!'"
    }
    
    logger.info("📝 Creating task using sync endpoint...")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            task_response = await client.post(
                f"{API_BASE_URL}/v1/agents/{agent_id}/tasks/sync",
                json=task_data
            )
            
            logger.info(f"Task creation response status: {task_response.status_code}")
            
            if task_response.status_code in [200, 201]:
                task = task_response.json()
                task_id = task["id"]
                logger.info(f"✅ Task created successfully: {task_id}")
                logger.info(f"   Status: {task['status']}")
                logger.info(f"   Description: {task['description']}")
                logger.info(f"   Execution ID: {task.get('execution_id', 'None')}")
                
                # Step 3: Check task status via API
                logger.info("🔍 Checking task status...")
                
                for attempt in range(5):
                    try:
                        status_response = await client.get(f"{API_BASE_URL}/v1/tasks/{task_id}")
                        
                        if status_response.status_code == 200:
                            task_status = status_response.json()
                            logger.info(f"📊 Attempt {attempt + 1}: Task status = {task_status['status']}")
                            
                            if task_status['status'] in ["completed", "failed"]:
                                logger.info(f"✅ Task finished with status: {task_status['status']}")
                                if 'result' in task_status and task_status['result']:
                                    logger.info(f"   Result: {task_status['result']}")
                                break
                        else:
                            logger.warning(f"⚠️ Failed to get task status: {status_response.status_code}")
                            
                    except Exception as e:
                        logger.warning(f"⚠️ Error checking task status: {e}")
                    
                    await asyncio.sleep(2)
                
                return True
                
            else:
                logger.error(f"❌ Failed to create task: {task_response.status_code}")
                logger.error(f"   Response: {task_response.text}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Error creating task: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_sync_task_creation())
    if success:
        print("\n🎉 Sync task creation test PASSED!")
    else:
        print("\n💥 Sync task creation test FAILED!")
        exit(1)