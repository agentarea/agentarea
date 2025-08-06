#!/usr/bin/env python3
"""
Test temporal workflow completion detection.
"""

import asyncio
import logging
from uuid import uuid4

from core.libs.execution.agentarea_execution.agentic.runners.temporal_runner import TemporalAgentRunner

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_temporal_completion():
    """Test temporal workflow completion detection."""
    logger.info("Starting temporal completion test...")
    
    # Create temporal runner
    runner = TemporalAgentRunner()
    
    # Test configuration
    agent_config = {
        "model_id": "mock_model",
        "system_prompt": "You are a test agent."
    }
    
    # Mock tools that include task_complete
    available_tools = [
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Signal that the task has been completed",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "The final result or summary"
                        }
                    },
                    "required": ["result"]
                }
            }
        }
    ]
    
    # Create a simple goal
    goal = "Complete a test task and signal completion"
    
    try:
        # Execute with temporal runner
        result = await runner.execute(
            goal=goal,
            agent_config=agent_config,
            available_tools=available_tools,
            max_iterations=5,
            mock_mode=True  # Use mock mode to avoid LLM calls
        )
        
        logger.info(f"Temporal Result:")
        logger.info(f"  Success: {result.success}")
        logger.info(f"  Iterations: {result.iterations_completed}")
        logger.info(f"  Final response: {result.final_response}")
        
        if result.success and result.iterations_completed == 1:
            logger.info("✅ Temporal completion detection working!")
            return True
        else:
            logger.error("❌ Temporal completion detection failed!")
            return False
            
    except Exception as e:
        logger.error(f"Temporal test failed: {e}")
        return False

async def main():
    """Run temporal completion tests."""
    logger.info("=== Testing Temporal Workflow Completion ===")
    
    success = await test_temporal_completion()
    
    if success:
        logger.info("🎉 Temporal completion test passed!")
    else:
        logger.error("💥 Temporal completion test failed!")
        
    return success

if __name__ == "__main__":
    asyncio.run(main())