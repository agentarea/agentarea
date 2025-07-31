#!/usr/bin/env python3
"""
Complete end-to-end test for task creation, workflow execution, SSE events, and API retrieval.
"""

import asyncio
import json
import logging
from datetime import datetime
from uuid import uuid4
import httpx
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE_URL = "http://localhost:8000"

async def test_complete_task_flow():
    """Test the complete task flow from creation to completion."""
    
    logger.info("🚀 Starting complete task flow test...")
    
    # Step 1: Create an agent first (required for task creation)
    logger.info("📝 Step 1: Creating an agent...")
    
    async with httpx.AsyncClient() as client:
        # Create agent
        agent_data = {
            "name": "Test Agent for Flow",
            "description": "Test agent for complete flow testing",
            "instruction": "You are a helpful assistant that responds to user queries.",
            "model_id": "test-model-id",  # We'll need to create this or use existing
            "planning": False
        }
        
        try:
            # First, let's check if we have any existing agents
            agents_response = await client.get(f"{API_BASE_URL}/v1/agents/")
            if agents_response.status_code == 200:
                agents = agents_response.json()
                if agents and len(agents) > 0:
                    agent_id = agents[0]["id"]
                    logger.info(f"✅ Using existing agent: {agent_id}")
                else:
                    logger.info("❌ No existing agents found, need to create one")
                    return
            else:
                logger.error(f"❌ Failed to list agents: {agents_response.status_code}")
                return
                
        except Exception as e:
            logger.error(f"❌ Error checking agents: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return
    
    # Step 2: Create a task
    logger.info("📝 Step 2: Creating a task...")
    
    async with httpx.AsyncClient() as client:
        task_data = {
            "description": "Test task for complete flow - please respond with 'Hello from the agent!'"
        }
        
        try:
            # Create task via API (this might be a streaming response)
            task_response = await client.post(
                f"{API_BASE_URL}/v1/agents/{agent_id}/tasks/",
                json=task_data,
                timeout=5.0  # Shorter timeout since we just want to start the task
            )
            
            logger.info(f"Task creation response status: {task_response.status_code}")
            logger.info(f"Task creation response: {task_response.text}")
            
            if task_response.status_code in [200, 201]:
                try:
                    task = task_response.json()
                    task_id = task["id"]
                    logger.info(f"✅ Task created successfully: {task_id}")
                    logger.info(f"   Status: {task['status']}")
                    logger.info(f"   Description: {task['description']}")
                except json.JSONDecodeError as je:
                    logger.error(f"❌ Failed to parse task response JSON: {je}")
                    logger.error(f"   Raw response: {task_response.text}")
                    return
                except KeyError as ke:
                    logger.error(f"❌ Missing key in task response: {ke}")
                    logger.error(f"   Response data: {task_response.json()}")
                    return
            else:
                logger.error(f"❌ Failed to create task: {task_response.status_code}")
                logger.error(f"   Response: {task_response.text}")
                return
                
        except Exception as e:
            if "ReadTimeout" in str(e):
                logger.info("⏳ Task creation timed out (likely because it's streaming), but task may have been created")
                # Let's try to find the task by listing all tasks
                try:
                    tasks_response = await client.get(f"{API_BASE_URL}/v1/tasks/")
                    if tasks_response.status_code == 200:
                        tasks = tasks_response.json()
                        # Find the most recent task
                        if tasks:
                            latest_task = max(tasks, key=lambda t: t.get('created_at', ''))
                            task_id = latest_task["id"]
                            logger.info(f"✅ Found latest task: {task_id}")
                        else:
                            logger.error("❌ No tasks found")
                            return
                    else:
                        logger.error("❌ Could not list tasks to find created task")
                        return
                except Exception as list_error:
                    logger.error(f"❌ Error listing tasks: {list_error}")
                    return
            else:
                logger.error(f"❌ Error creating task: {e}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                return
    
    # Step 3: Monitor task execution via SSE (simulate)
    logger.info("📡 Step 3: Monitoring task execution...")
    
    # Wait a bit for workflow to start
    await asyncio.sleep(2)
    
    # Step 4: Check task status via API
    logger.info("🔍 Step 4: Checking task status via API...")
    
    max_attempts = 10
    attempt = 0
    
    async with httpx.AsyncClient() as client:
        while attempt < max_attempts:
            try:
                # Get task status
                task_response = await client.get(f"{API_BASE_URL}/v1/tasks/{task_id}")
                
                if task_response.status_code == 200:
                    task = task_response.json()
                    status = task["status"]
                    logger.info(f"📊 Attempt {attempt + 1}: Task status = {status}")
                    
                    if status in ["completed", "failed"]:
                        logger.info(f"✅ Task finished with status: {status}")
                        
                        # Show task details
                        logger.info("📋 Final task details:")
                        logger.info(f"   ID: {task['id']}")
                        logger.info(f"   Status: {task['status']}")
                        logger.info(f"   Description: {task['description']}")
                        logger.info(f"   Created: {task['created_at']}")
                        logger.info(f"   Updated: {task['updated_at']}")
                        
                        if 'result' in task and task['result']:
                            logger.info(f"   Result: {task['result']}")
                        
                        break
                    elif status == "running":
                        logger.info("⏳ Task is still running, waiting...")
                        await asyncio.sleep(3)
                    else:
                        logger.info(f"📝 Task status: {status}, continuing to monitor...")
                        await asyncio.sleep(2)
                        
                else:
                    logger.error(f"❌ Failed to get task status: {task_response.status_code}")
                    logger.error(f"   Response: {task_response.text}")
                    break
                    
            except Exception as e:
                logger.error(f"❌ Error checking task status: {e}")
                break
                
            attempt += 1
    
    if attempt >= max_attempts:
        logger.warning("⚠️ Reached maximum attempts, task may still be running")
    
    # Step 5: Test SSE endpoint (basic connectivity test)
    logger.info("📡 Step 5: Testing SSE endpoint connectivity...")
    
    try:
        async with httpx.AsyncClient() as client:
            # Test SSE endpoint with a short timeout
            sse_response = await client.get(
                f"{API_BASE_URL}/v1/tasks/{task_id}/events",
                timeout=5.0
            )
            
            if sse_response.status_code == 200:
                logger.info("✅ SSE endpoint is accessible")
                # Read first few bytes to confirm it's working
                content = sse_response.text[:200] if sse_response.text else "No content"
                logger.info(f"   SSE content preview: {content}")
            else:
                logger.error(f"❌ SSE endpoint failed: {sse_response.status_code}")
                
    except httpx.TimeoutException:
        logger.info("⏳ SSE endpoint timeout (expected for streaming)")
    except Exception as e:
        logger.error(f"❌ Error testing SSE endpoint: {e}")
    
    # Step 6: List all tasks to verify our task is there
    logger.info("📋 Step 6: Listing all tasks...")
    
    async with httpx.AsyncClient() as client:
        try:
            tasks_response = await client.get(f"{API_BASE_URL}/v1/tasks/")
            
            if tasks_response.status_code == 200:
                tasks = tasks_response.json()
                logger.info(f"✅ Found {len(tasks)} total tasks")
                
                # Find our task
                our_task = next((t for t in tasks if t["id"] == task_id), None)
                if our_task:
                    logger.info(f"✅ Our task found in list: {our_task['status']}")
                else:
                    logger.warning("⚠️ Our task not found in list")
                    
            else:
                logger.error(f"❌ Failed to list tasks: {tasks_response.status_code}")
                
        except Exception as e:
            logger.error(f"❌ Error listing tasks: {e}")
    
    logger.info("🎉 Complete task flow test finished!")

if __name__ == "__main__":
    asyncio.run(test_complete_task_flow())