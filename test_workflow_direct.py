#!/usr/bin/env python3
"""
Test workflow directly through Temporal client.
"""

import asyncio
import logging
from uuid import uuid4

from temporalio.client import Client

from core.libs.execution.agentarea_execution.models import AgentExecutionRequest
from core.libs.execution.agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_workflow_completion():
    """Test workflow completion detection."""
    logger.info("Starting workflow completion test...")
    
    try:
        # Connect to Temporal
        client = await Client.connect("localhost:7233")
        
        # Create test request
        request = AgentExecutionRequest(
            agent_id=uuid4(),
            task_id=uuid4(),
            user_id="test-user",
            task_query="Complete a simple test task",
            task_parameters={
                "max_iterations": 3,
                "success_criteria": ["Task completed successfully"]
            },
            requires_human_approval=False,
            budget_usd=1.0
        )
        
        # Start workflow
        workflow_id = f"test-completion-{uuid4()}"
        handle = await client.start_workflow(
            AgentExecutionWorkflow.run,
            request,
            id=workflow_id,
            task_queue="agent-tasks"  # Use correct task queue
        )
        
        logger.info(f"Started workflow: {workflow_id}")
        
        # Wait for result with timeout
        try:
            result = await asyncio.wait_for(handle.result(), timeout=60.0)
            logger.info(f"Workflow completed!")
            logger.info(f"  Success: {result.success}")
            logger.info(f"  Iterations: {result.reasoning_iterations_used}")
            logger.info(f"  Final response: {result.final_response}")
            
            return result.success
            
        except asyncio.TimeoutError:
            logger.error("Workflow timed out!")
            return False
            
    except Exception as e:
        logger.error(f"Workflow test failed: {e}")
        return False

async def main():
    """Run workflow completion test."""
    logger.info("=== Testing Workflow Completion Detection ===")
    
    success = await test_workflow_completion()
    
    if success:
        logger.info("🎉 Workflow completion test passed!")
    else:
        logger.error("💥 Workflow completion test failed!")
        
    return success

if __name__ == "__main__":
    asyncio.run(main())