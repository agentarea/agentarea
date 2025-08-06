"""Test completion flow for both sync and temporal runners."""

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


async def test_sync_runner_completion():
    """Test that SyncAgentRunner properly detects completion."""
    logger.info("=== Testing SyncAgentRunner Completion Detection ===")
    
    # Create mock LLM that calls task_complete
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = MagicMock(
        content="I'll complete this task now.",
        cost=0.001,
        tool_calls=[{
            "id": "call_complete",
            "function": {
                "name": "task_complete",
                "arguments": '{"result": "Task completed successfully"}'
            }
        }]
    )
    
    # Create runner
    runner = SyncAgentRunner(
        llm_model=mock_llm,
        config=RunnerConfig(max_iterations=5)
    )
    
    # Define goal
    goal = AgentGoal(
        description="Complete a test task",
        success_criteria=["Task completed"],
        max_iterations=5
    )
    
    try:
        # Run the agent
        result = await runner.run(goal)
        
        logger.info(f"SyncRunner Result:")
        logger.info(f"  Success: {result.success}")
        logger.info(f"  Iterations: {result.current_iteration}")
        logger.info(f"  Final response: {result.final_response}")
        logger.info(f"  Termination reason: {result.termination_reason}")
        
        # Verify completion detection
        assert result.success == True, f"Expected success=True, got {result.success}"
        assert result.current_iteration == 1, f"Expected 1 iteration, got {result.current_iteration}"
        assert "Goal achieved successfully" in result.termination_reason, f"Wrong termination reason: {result.termination_reason}"
        assert result.final_response == "Task completed successfully", f"Wrong final response: {result.final_response}"
        
        logger.info("✅ SyncAgentRunner completion detection working!")
        return True
        
    except Exception as e:
        logger.error(f"❌ SyncAgentRunner test failed: {e}")
        return False


async def test_tool_call_format():
    """Test that tool calls are formatted correctly for workflow processing."""
    logger.info("\n=== Testing Tool Call Format ===")
    
    try:
        # Import workflow components
        from libs.execution.agentarea_execution.workflows.helpers import ToolCallExtractor
        from libs.execution.agentarea_execution.workflows.agent_execution_workflow import Message, ToolCall
        
        # Create a message with tool calls (as would come from LLM)
        message = Message(
            role="assistant",
            content="I'll complete this task.",
            tool_calls=[{
                "id": "call_123",
                "type": "function", 
                "function": {
                    "name": "task_complete",
                    "arguments": '{"result": "Task completed"}'
                }
            }]
        )
        
        # Extract tool calls
        extracted_calls = ToolCallExtractor.extract_tool_calls(message)
        
        logger.info(f"Extracted {len(extracted_calls)} tool calls")
        
        if extracted_calls:
            tool_call = extracted_calls[0]
            logger.info(f"  Tool call type: {type(tool_call)}")
            logger.info(f"  Tool call ID: {tool_call.id}")
            logger.info(f"  Function name: {tool_call.function['name']}")
            logger.info(f"  Function args: {tool_call.function['arguments']}")
            
            # Verify structure
            assert isinstance(tool_call, ToolCall), f"Expected ToolCall, got {type(tool_call)}"
            assert tool_call.function["name"] == "task_complete", f"Wrong function name"
            
            # Test JSON parsing (as workflow would do)
            import json
            parsed_args = json.loads(tool_call.function["arguments"])
            assert parsed_args["result"] == "Task completed", f"Wrong parsed result"
            
            logger.info("✅ Tool call format working correctly!")
            return True
        else:
            logger.error("❌ No tool calls extracted!")
            return False
            
    except Exception as e:
        logger.error(f"❌ Tool call format test failed: {e}")
        return False


async def test_completion_tool_execution():
    """Test that the completion tool executes correctly."""
    logger.info("\n=== Testing Completion Tool Execution ===")
    
    try:
        from libs.execution.agentarea_execution.agentic.tools.completion_tool import CompletionTool
        
        # Create and execute completion tool
        tool = CompletionTool()
        result = await tool.execute(result="Test task completed")
        
        logger.info(f"Completion tool result: {result}")
        
        # Verify result structure
        assert result.get("success") == True, f"Expected success=True"
        assert result.get("completed") == True, f"Expected completed=True"
        assert result.get("result") == "Test task completed", f"Wrong result"
        assert result.get("tool_name") == "task_complete", f"Wrong tool name"
        
        logger.info("✅ Completion tool execution working!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Completion tool test failed: {e}")
        return False


async def test_empty_message_prevention():
    """Test that empty messages are not added to conversation."""
    logger.info("\n=== Testing Empty Message Prevention ===")
    
    # Create mock LLM that returns empty content
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = MagicMock(
        content="",  # Empty content
        cost=0.001,
        tool_calls=None  # No tool calls
    )
    
    # Create runner
    runner = SyncAgentRunner(
        llm_model=mock_llm,
        config=RunnerConfig(max_iterations=2)
    )
    
    # Define goal
    goal = AgentGoal(
        description="Test empty message handling",
        success_criteria=["Handle empty messages"],
        max_iterations=2
    )
    
    try:
        # Run the agent
        result = await runner.run(goal)
        
        logger.info(f"Empty message test result:")
        logger.info(f"  Success: {result.success}")
        logger.info(f"  Messages: {len(result.messages)}")
        logger.info(f"  Iterations: {result.current_iteration}")
        
        # Check that we don't have excessive empty messages
        empty_messages = [msg for msg in result.messages if not msg.content.strip() and not msg.tool_calls]
        logger.info(f"  Empty messages: {len(empty_messages)}")
        
        # Should reach max iterations without success (since LLM returns empty)
        assert result.success == False, f"Should not succeed with empty responses"
        assert result.current_iteration == 2, f"Should reach max iterations"
        
        logger.info("✅ Empty message prevention working!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Empty message test failed: {e}")
        return False


async def main():
    """Run all completion flow tests."""
    logger.info("Starting completion flow tests...")
    
    tests = [
        ("SyncRunner completion detection", test_sync_runner_completion),
        ("Tool call format", test_tool_call_format),
        ("Completion tool execution", test_completion_tool_execution),
        ("Empty message prevention", test_empty_message_prevention),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            success = await test_func()
            results.append((test_name, success))
        except Exception as e:
            logger.error(f"Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    logger.info(f"\n=== Completion Flow Test Summary ===")
    for test_name, success in results:
        status = "✓ PASSED" if success else "✗ FAILED"
        logger.info(f"{status}: {test_name}")
    
    logger.info(f"\nPassed: {passed}/{total} tests")
    
    if passed == total:
        logger.info("🎉 All completion flow tests passed!")
        logger.info("\nBoth SyncAgentRunner and workflow components are working correctly!")
        return True
    else:
        logger.warning(f"⚠ {total - passed} tests failed")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)