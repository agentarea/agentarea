#!/usr/bin/env python3
"""Debug tool parameter mismatch between what LLM sends vs what CompletionTool expects.
"""

import asyncio
import logging

from agentarea_agents_sdk.tools.tool_executor import ToolExecutor

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_tool_parameter_mismatch():
    """Test what happens when LLM sends different parameters than expected."""
    logger.info("🔧 Testing Tool Parameter Mismatch")
    logger.info("=" * 60)

    executor = ToolExecutor()

    # Test 1: LLM sends simple result + success (common pattern)
    logger.info("\n📋 Test 1: LLM sends simple result + success")
    logger.info("-" * 40)

    simple_args = {
        "result": "Task completed successfully",
        "success": True
    }

    logger.info(f"Calling task_complete with: {simple_args}")

    try:
        result1 = await executor.execute_tool("task_complete", simple_args)
        logger.info(f"Result: {result1}")
        logger.info(f"Success: {result1.get('success')}")
        logger.info(f"Completed: {result1.get('completed')}")
    except Exception as e:
        logger.error(f"Error: {e}")

    # Test 2: LLM sends proper CompletionTool format
    logger.info("\n📋 Test 2: LLM sends proper CompletionTool format")
    logger.info("-" * 40)

    proper_args = {
        "summary": "I completed the user's request successfully",
        "reasoning": "All requirements were met and the task is finished",
        "result": "Task completed with full success"
    }

    logger.info(f"Calling task_complete with: {proper_args}")

    try:
        result2 = await executor.execute_tool("task_complete", proper_args)
        logger.info(f"Result: {result2}")
        logger.info(f"Success: {result2.get('success')}")
        logger.info(f"Completed: {result2.get('completed')}")
    except Exception as e:
        logger.error(f"Error: {e}")

    # Test 3: Mixed parameters
    logger.info("\n📋 Test 3: LLM sends mixed parameters")
    logger.info("-" * 40)

    mixed_args = {
        "result": "Task finished",
        "success": True,
        "reasoning": "Everything looks good"
        # Missing "summary" - required parameter
    }

    logger.info(f"Calling task_complete with: {mixed_args}")

    try:
        result3 = await executor.execute_tool("task_complete", mixed_args)
        logger.info(f"Result: {result3}")
        logger.info(f"Success: {result3.get('success')}")
        logger.info(f"Completed: {result3.get('completed')}")
    except Exception as e:
        logger.error(f"Error: {e}")

    # Analysis
    logger.info("\n📊 Analysis")
    logger.info("=" * 60)

    logger.info("CompletionTool expects: summary, reasoning, result (all required)")
    logger.info("LLM typically sends: result, success (from other AI frameworks)")
    logger.info("")
    logger.info("This mismatch could cause:")
    logger.info("1. Tool execution to use default values")
    logger.info("2. Missing required parameters to be filled with defaults")
    logger.info("3. Workflow to not detect completion properly")

    return True

if __name__ == "__main__":
    # Run the test
    result = asyncio.run(test_tool_parameter_mismatch())

    print("\n" + "=" * 80)
    print("🔍 TOOL PARAMETER MISMATCH ANALYSIS COMPLETE")
    print("")
    print("Check the logs above to see how the CompletionTool handles")
    print("different parameter formats from the LLM.")
    print("")
    print("If the tool uses defaults for missing parameters, the workflow")
    print("completion detection should still work - but the LLM might")
    print("not be getting proper feedback about parameter expectations.")
