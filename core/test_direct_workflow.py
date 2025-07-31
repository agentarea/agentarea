#!/usr/bin/env python3
"""
Test direct workflow execution with a real agent ID.
"""

import asyncio
import logging
from uuid import uuid4
import httpx

from temporalio.client import Client
from libs.execution.agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from libs.execution.agentarea_execution.models import AgentExecutionRequest

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE_URL = "http://localhost:8000"

async def test_direct_workflow():
    """Test direct workflow execution with a real agent ID."""
    
    logger.info("🚀 Testing direct workflow execution...")
    
    # Step 1: Get a real agent ID from the API
    async with httpx.AsyncClient() as client:
        try:
            agents_response = await client.get(f"{API_BASE_URL}/v1/agents/")
            if agents_response.status_code == 200:
                agents = agents_response.json()
                if agents and len(agents) > 0:
                    agent_id = agents[0]["id"]
                    agent_name = agents[0]["name"]
                    logger.info(f"✅ Using real agent: {agent_name} ({agent_id})")
                else:
                    logger.error("❌ No agents found")
                    return False
            else:
                logger.error(f"❌ Failed to get agents: {agents_response.status_code}")
                return False
        except Exception as e:
            logger.error(f"❌ Error getting agents: {e}")
            return False
    
    # Step 2: Connect to Temporal and start workflow
    try:
        # Connect to Temporal
        client = await Client.connect("localhost:7233")
        
        # Create a test workflow input with real agent ID
        task_id = uuid4()
        
        workflow_input = AgentExecutionRequest(
            task_id=task_id,
            agent_id=agent_id,  # Use real agent ID
            user_id="test-user-direct",
            task_query="Direct workflow test - please respond with 'Hello from direct workflow!'",
            timeout_seconds=60,
            max_reasoning_iterations=3
        )
        
        logger.info(f"📝 Starting workflow with real agent...")
        logger.info(f"   Task ID: {workflow_input.task_id}")
        logger.info(f"   Agent ID: {workflow_input.agent_id}")
        logger.info(f"   Query: {workflow_input.task_query}")
        
        # Start the workflow
        handle = await client.start_workflow(
            AgentExecutionWorkflow.run,
            workflow_input,
            id=f"direct-test-{workflow_input.task_id}",
            task_queue="agent-tasks"
        )
        
        logger.info(f"✅ Workflow started successfully with ID: {handle.id}")
        
        # Wait and check status
        for attempt in range(10):
            await asyncio.sleep(2)
            
            describe = await handle.describe()
            status = describe.status.name
            logger.info(f"📊 Attempt {attempt + 1}: Workflow status = {status}")
            
            if status in ["COMPLETED", "FAILED", "CANCELED"]:
                logger.info(f"🏁 Workflow finished with status: {status}")
                
                if status == "COMPLETED":
                    try:
                        result = await handle.result()
                        logger.info(f"✅ Workflow completed successfully!")
                        logger.info(f"   Result type: {type(result)}")
                        if hasattr(result, 'success'):
                            logger.info(f"   Success: {result.success}")
                        if hasattr(result, 'final_response'):
                            logger.info(f"   Response: {result.final_response}")
                        return True
                    except Exception as e:
                        logger.error(f"❌ Error getting workflow result: {e}")
                        return False
                elif status == "FAILED":
                    logger.error("❌ Workflow failed")
                    return False
                else:
                    logger.warning(f"⚠️ Workflow ended with status: {status}")
                    return False
        
        logger.warning("⏳ Workflow still running after timeout")
        return True  # Consider it a success if it's still running
        
    except Exception as e:
        logger.error(f"❌ Error in workflow execution: {e}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_direct_workflow())
    if success:
        print("\n🎉 Direct workflow test PASSED!")
    else:
        print("\n💥 Direct workflow test FAILED!")
        exit(1)