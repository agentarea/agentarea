"""Test to verify that agents complete via LLM decision vs iteration limits."""

import asyncio
import logging
import sys
from unittest.mock import AsyncMock, MagicMock

# Add core to path for imports
sys.path.insert(0, "core")

from libs.execution.agentarea_execution.agentic import (
    LLMModel,
    SyncAgentRunner,
    RunnerConfig,
    ToolExecutor,
)
from libs.execution.agentarea_execution.agentic.runners.base import AgentGoal

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_llm_driven_completion():
    """Test that shows LLM-driven completion vs iteration limit."""
    logger.info("=== Testing LLM-Driven Completion vs Iteration Limits ===")
    
    # Test 1: LLM decides to complete (with high iteration limit)
    logger.info("\n--- Test 1: LLM Decides to Complete ---")
    
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = MagicMock(
        content="I'll complete this task now.",
        cost=0.001,
        tool_calls=[{
            "id": "call_complete",
            "function": {
                "name": "task_complete",
                "arguments": '{"result": "Task completed by LLM decision"}'
            }
        }]
    )
    
    runner = SyncAgentRunner(
        llm_model=mock_llm,
        config=RunnerConfig(max_iterations=10)  # High limit - should not be reached
    )
    
    goal = AgentGoal(
        description="Complete a simple task",
        success_criteria=["Task completed"],
        max_iterations=10  # High limit
    )
    
    result = await runner.run(goal)
    
    logger.info(f"Result: Success={result.success}, Iterations={result.current_iteration}")
    logger.info(f"Termination reason: {result.termination_reason}")
    logger.info(f"Final response: {result.final_response}")
    
    # Verify this was LLM-driven completion, not iteration limit
    assert result.success == True, "Should succeed via LLM completion"
    assert result.current_iteration < 10, "Should complete before hitting iteration limit"
    assert "Goal achieved successfully" in result.termination_reason, "Should terminate due to goal achievement"
    assert result.final_response == "Task completed by LLM decision", "Should have LLM's completion message"
    
    logger.info("✓ LLM-driven completion verified!")
    
    # Test 2: Iteration limit reached (LLM never completes)
    logger.info("\n--- Test 2: Iteration Limit Reached ---")
    
    mock_llm_no_complete = AsyncMock()
    mock_llm_no_complete.complete.return_value = MagicMock(
        content="I'm still working on this...",
        cost=0.001,
        tool_calls=None  # Never calls completion tool
    )
    
    runner2 = SyncAgentRunner(
        llm_model=mock_llm_no_complete,
        config=RunnerConfig(max_iterations=3)  # Low limit
    )
    
    goal2 = AgentGoal(
        description="Complete an impossible task",
        success_criteria=["Achieve the impossible"],
        max_iterations=3  # Low limit
    )
    
    result2 = await runner2.run(goal2)
    
    logger.info(f"Result: Success={result2.success}, Iterations={result2.current_iteration}")
    logger.info(f"Termination reason: {result2.termination_reason}")
    logger.info(f"Final response: {result2.final_response}")
    
    # Verify this was iteration limit, not LLM completion
    assert result2.success == False, "Should not succeed"
    assert result2.current_iteration == 3, "Should hit iteration limit"
    assert "Maximum iterations reached" in result2.termination_reason, "Should terminate due to iteration limit"
    assert result2.final_response is None, "Should have no completion message"
    
    logger.info("✓ Iteration limit termination verified!")
    
    # Test 3: Mixed scenario - LLM completes after some iterations
    logger.info("\n--- Test 3: LLM Completes After Multiple Iterations ---")
    
    # Mock LLM that works for a few iterations then completes
    responses = [
        # Iteration 1: Working
        MagicMock(content="Let me work on this...", cost=0.001, tool_calls=None),
        # Iteration 2: Still working  
        MagicMock(content="Making progress...", cost=0.001, tool_calls=None),
        # Iteration 3: Completes
        MagicMock(
            content="Done! I'll signal completion now.",
            cost=0.001,
            tool_calls=[{
                "id": "call_final",
                "function": {
                    "name": "task_complete", 
                    "arguments": '{"result": "Completed after 3 iterations"}'
                }
            }]
        )
    ]
    
    mock_llm_delayed = AsyncMock()
    mock_llm_delayed.complete.side_effect = responses
    
    runner3 = SyncAgentRunner(
        llm_model=mock_llm_delayed,
        config=RunnerConfig(max_iterations=10)  # High limit
    )
    
    goal3 = AgentGoal(
        description="Complete task after some work",
        success_criteria=["Task completed after iterations"],
        max_iterations=10
    )
    
    result3 = await runner3.run(goal3)
    
    logger.info(f"Result: Success={result3.success}, Iterations={result3.current_iteration}")
    logger.info(f"Termination reason: {result3.termination_reason}")
    logger.info(f"Final response: {result3.final_response}")
    
    # Verify this was LLM completion after multiple iterations
    assert result3.success == True, "Should succeed via LLM completion"
    assert result3.current_iteration == 3, "Should complete after 3 iterations"
    assert "Goal achieved successfully" in result3.termination_reason, "Should terminate due to goal achievement"
    assert result3.final_response == "Completed after 3 iterations", "Should have final completion message"
    
    logger.info("✓ Multi-iteration LLM completion verified!")
    
    return True


async def main():
    """Run completion verification tests."""
    logger.info("Starting completion verification tests...")
    
    try:
        success = await test_llm_driven_completion()
        
        if success:
            logger.info("\n🎉 All completion verification tests passed!")
            logger.info("\nConclusion:")
            logger.info("✓ Agents can complete via LLM decision (task_complete tool)")
            logger.info("✓ Agents properly terminate at iteration limits when needed")
            logger.info("✓ Termination reasons are correctly reported")
            logger.info("✓ The system distinguishes between success and timeout")
            return True
        else:
            logger.error("❌ Some tests failed")
            return False
            
    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)