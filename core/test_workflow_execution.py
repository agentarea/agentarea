#!/usr/bin/env python3
"""
Direct workflow execution test to verify the user_context_data fix.
"""

import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from temporalio.client import Client
from temporalio.worker import Worker

from libs.execution.agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from libs.execution.agentarea_execution.models import AgentExecutionRequest

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_workflow_execution():
    """Test workflow execution with proper user context data."""
    
    # Connect to Temporal
    client = await Client.connect("localhost:7233")
    
    # Create a test workflow input
    task_id = uuid4()
    agent_id = uuid4()
    
    workflow_input = AgentExecutionRequest(
        task_id=task_id,
        agent_id=agent_id,
        user_id="test-user-123",
        task_query="Test workflow execution with fixed user context",
        timeout_seconds=300,
        max_reasoning_iterations=5
    )
    
    logger.info(f"🚀 Starting workflow execution test...")
    logger.info(f"Task ID: {workflow_input.task_id}")
    logger.info(f"Agent ID: {workflow_input.agent_id}")
    
    try:
        # Start the workflow
        handle = await client.start_workflow(
            AgentExecutionWorkflow.run,
            workflow_input,
            id=f"test-workflow-{workflow_input.task_id}",
            task_queue="agent-tasks"  # Use the correct task queue that matches the worker
        )
        
        logger.info(f"✅ Workflow started with ID: {handle.id}")
        
        # Wait for a short time to see if it starts properly
        await asyncio.sleep(5)
        
        # Check workflow status
        describe = await handle.describe()
        logger.info(f"📊 Workflow status: {describe.status}")
        
        if describe.status.name == "RUNNING":
            logger.info("✅ Workflow is running successfully!")
            
            # Let it run for a bit more
            await asyncio.sleep(10)
            
            # Check again
            describe = await handle.describe()
            logger.info(f"📊 Final workflow status: {describe.status}")
            
        else:
            logger.error(f"❌ Workflow failed to start properly: {describe.status}")
            
    except Exception as e:
        logger.error(f"❌ Workflow execution failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(test_workflow_execution())