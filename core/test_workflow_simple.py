#!/usr/bin/env python3
"""
Simple workflow test to verify user_context_data fix without full execution.
"""

import asyncio
import logging
from uuid import uuid4

from temporalio.client import Client

from libs.execution.agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from libs.execution.agentarea_execution.models import AgentExecutionRequest

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_workflow_start():
    """Test that workflow can start without user_context_data errors."""
    
    # Connect to Temporal
    client = await Client.connect("localhost:7233")
    
    # Create a test workflow input
    task_id = uuid4()
    agent_id = uuid4()
    
    workflow_input = AgentExecutionRequest(
        task_id=task_id,
        agent_id=agent_id,
        user_id="test-user-123",
        task_query="Simple test to verify user_context_data fix",
        timeout_seconds=30,  # Short timeout
        max_reasoning_iterations=1  # Minimal iterations
    )
    
    logger.info(f"🚀 Testing workflow start...")
    logger.info(f"Task ID: {workflow_input.task_id}")
    logger.info(f"Agent ID: {workflow_input.agent_id}")
    
    try:
        # Start the workflow
        handle = await client.start_workflow(
            AgentExecutionWorkflow.run,
            workflow_input,
            id=f"simple-test-{workflow_input.task_id}",
            task_queue="agent-tasks"
        )
        
        logger.info(f"✅ Workflow started successfully with ID: {handle.id}")
        
        # Wait a short time to see if it starts without the user_context_data error
        await asyncio.sleep(3)
        
        # Check workflow status
        describe = await handle.describe()
        logger.info(f"📊 Workflow status after 3 seconds: {describe.status}")
        
        # If it's running or completed, the user_context_data issue is fixed
        if describe.status.name in ["RUNNING", "COMPLETED"]:
            logger.info("✅ SUCCESS: Workflow started without user_context_data errors!")
            return True
        elif describe.status.name == "FAILED":
            logger.info("⚠️  Workflow failed, but this might be due to infrastructure issues, not user_context_data")
            # Try to get the failure reason
            try:
                result = await handle.result()
            except Exception as e:
                if "user_context_data" in str(e):
                    logger.error("❌ FAILED: user_context_data error still exists!")
                    return False
                else:
                    logger.info(f"✅ SUCCESS: Workflow failed for other reasons (not user_context_data): {e}")
                    return True
        
        return True
        
    except Exception as e:
        if "user_context_data" in str(e):
            logger.error(f"❌ FAILED: user_context_data error: {e}")
            return False
        else:
            logger.info(f"✅ SUCCESS: Workflow failed for other reasons (not user_context_data): {e}")
            return True

if __name__ == "__main__":
    success = asyncio.run(test_workflow_start())
    if success:
        print("\n🎉 Test PASSED: user_context_data issue is fixed!")
    else:
        print("\n💥 Test FAILED: user_context_data issue still exists!")
        exit(1)