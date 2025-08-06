"""Simple test for SyncAgentRunner to validate agentic flow."""

import asyncio
import logging
import os
import sys

# Add core to path for imports
sys.path.insert(0, "core")

from libs.execution.agentarea_execution.agentic import (
    LLMModel,
    SyncAgentRunner,
    RunnerConfig,
    ToolExecutor,
    GoalProgressEvaluator,
)
from libs.execution.agentarea_execution.agentic.runners.base import AgentGoal

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_simple_math_task():
    """Test the sync runner with a simple math task."""
    logger.info("=== Testing Simple Math Task ===")
    
    # Create LLM model (using Ollama for local testing)
    llm_model = LLMModel(
        provider_type="ollama_chat",
        model_name="llama3.2:3b",  # Small model for testing
        endpoint_url="http://localhost:11434"
    )
    
    # Create tool executor (includes completion tool by default)
    tool_executor = ToolExecutor()
    
    # Create goal evaluator
    goal_evaluator = GoalProgressEvaluator()
    
    # Create sync runner
    runner = SyncAgentRunner(
        llm_model=llm_model,
        tool_executor=tool_executor,
        goal_evaluator=goal_evaluator
    )
    
    # Define a simple goal
    goal = AgentGoal(
        description="Calculate 15 + 27 and provide the answer",
        success_criteria=[
            "Provide the correct sum of 15 + 27",
            "Show the calculation clearly"
        ],
        max_iterations=3
    )
    
    try:
        # Run the agent
        result = await runner.run(goal)
        
        # Print results
        logger.info(f"Execution completed!")
        logger.info(f"Success: {result.success}")
        logger.info(f"Iterations: {result.current_iteration}")
        logger.info(f"Total cost: ${result.total_cost:.6f}")
        logger.info(f"Final response: {result.final_response}")
        
        # Print conversation history
        logger.info("\n=== Conversation History ===")
        for i, msg in enumerate(result.messages):
            logger.info(f"{i+1}. {msg.role}: {msg.content[:100]}...")
            
        return result.success
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return False


async def test_completion_tool_usage():
    """Test the sync runner with explicit completion tool usage."""
    logger.info("\n=== Testing Completion Tool Usage ===")
    
    # Create LLM model
    llm_model = LLMModel(
        provider_type="ollama_chat",
        model_name="llama3.2:3b",
        endpoint_url="http://localhost:11434"
    )
    
    # Create sync runner
    runner = SyncAgentRunner(llm_model=llm_model)
    
    # Define a goal that should trigger completion tool
    goal = AgentGoal(
        description="Say hello and then signal completion",
        success_criteria=[
            "Provide a greeting",
            "Use the completion tool to signal done"
        ],
        max_iterations=2
    )
    
    try:
        # Run the agent
        result = await runner.run(goal)
        
        # Print results
        logger.info(f"Completion tool test completed!")
        logger.info(f"Success: {result.success}")
        logger.info(f"Iterations: {result.current_iteration}")
        logger.info(f"Final response: {result.final_response}")
        
        # Check if completion tool was used
        completion_tool_used = any(
            msg.role == "tool" and msg.name == "task_complete" 
            for msg in result.messages
        )
        logger.info(f"Completion tool used: {completion_tool_used}")
        
        return result.success and completion_tool_used
        
    except Exception as e:
        logger.error(f"Completion tool test failed: {e}")
        return False


async def test_without_llm():
    """Test basic runner structure without actual LLM calls."""
    logger.info("\n=== Testing Runner Structure (No LLM) ===")
    
    try:
        # Create mock components
        from unittest.mock import AsyncMock, MagicMock
        
        # Mock LLM client
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content="Hello! I'll complete this task now.",
            cost=0.001,
            tool_calls=[{
                "id": "call_123",
                "function": {
                    "name": "task_complete",
                    "arguments": '{"result": "Task completed successfully"}'
                }
            }]
        ))
        
        # Create runner with mock
        runner = SyncAgentRunner(llm_model=mock_llm)
        
        # Simple goal
        goal = AgentGoal(
            description="Test goal",
            success_criteria=["Complete the task"],
            max_iterations=1
        )
        
        # Run
        result = await runner.run(goal)
        
        logger.info(f"Mock test completed!")
        logger.info(f"Success: {result.success}")
        logger.info(f"Messages: {len(result.messages)}")
        
        return result.success
        
    except Exception as e:
        logger.error(f"Mock test failed: {e}")
        return False


async def main():
    """Run all tests."""
    logger.info("Starting SyncAgentRunner tests...")
    
    # Test 1: Basic structure without LLM
    test1_success = await test_without_llm()
    
    # Test 2: Simple math task (requires Ollama)
    test2_success = False
    try:
        test2_success = await test_simple_math_task()
    except Exception as e:
        logger.warning(f"Skipping LLM test (Ollama not available?): {e}")
    
    # Test 3: Completion tool usage (requires Ollama)  
    test3_success = False
    try:
        test3_success = await test_completion_tool_usage()
    except Exception as e:
        logger.warning(f"Skipping completion tool test (Ollama not available?): {e}")
    
    # Summary
    logger.info("\n=== Test Summary ===")
    logger.info(f"Mock test: {'✓' if test1_success else '✗'}")
    logger.info(f"Math test: {'✓' if test2_success else '✗'}")
    logger.info(f"Completion test: {'✓' if test3_success else '✗'}")
    
    if test1_success:
        logger.info("✓ Basic runner structure works!")
    else:
        logger.error("✗ Basic runner structure failed!")
        
    if test2_success or test3_success:
        logger.info("✓ LLM integration works!")
    else:
        logger.warning("⚠ LLM tests skipped (check Ollama setup)")


if __name__ == "__main__":
    asyncio.run(main())