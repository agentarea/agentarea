#!/usr/bin/env python3
"""Simple test to verify interception is working."""

import asyncio
import logging
from unittest.mock import MagicMock, patch

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_simple_interception():
    """Test that interception works by directly calling patched methods."""
    logger.info("🎯 SIMPLE INTERCEPTION TEST")
    logger.info("=" * 40)
    
    # Import and enable interception
    from agentarea_execution.adk_temporal.interceptors import enable_temporal_backbone
    from agentarea_execution.ag.adk.tools.base_tool import BaseTool
    from agentarea_execution.ag.adk.models.base_llm import BaseLlm
    from agentarea_execution.ag.adk.tools.tool_context import ToolContext
    from agentarea_execution.ag.adk.models.llm_request import LlmRequest
    from google.genai import types
    
    # Store original methods
    original_tool_method = BaseTool.run_async
    original_llm_method = BaseLlm.generate_content_async
    
    logger.info(f"Original tool method: {original_tool_method}")
    logger.info(f"Original LLM method: {original_llm_method}")
    
    # Enable interception
    logger.info("\n🔧 Enabling interception...")
    enable_temporal_backbone()
    
    # Check if methods were replaced
    new_tool_method = BaseTool.run_async
    new_llm_method = BaseLlm.generate_content_async
    
    logger.info(f"New tool method: {new_tool_method}")
    logger.info(f"New LLM method: {new_llm_method}")
    
    tool_patched = new_tool_method != original_tool_method
    llm_patched = new_llm_method != original_llm_method
    
    logger.info(f"✅ Tool method patched: {tool_patched}")
    logger.info(f"✅ LLM method patched: {llm_patched}")
    
    if not (tool_patched and llm_patched):
        logger.error("❌ Methods were not patched!")
        return False
    
    # Test without workflow context (should fall back)
    logger.info("\n🔍 Testing without workflow context...")
    
    # Create a simple tool instance
    class SimpleTestTool(BaseTool):
        def __init__(self):
            super().__init__(name="simple_test", description="Simple test tool")
    
    tool = SimpleTestTool()
    tool_context = MagicMock(spec=ToolContext)
    
    try:
        # This should call the interceptor, which should fall back to original
        result = await tool.run_async(args={"test": "no_workflow"}, tool_context=tool_context)
        logger.info(f"Tool result (no workflow): {result}")
    except Exception as e:
        logger.info(f"Tool call failed (expected): {e}")
    
    # Test with mocked workflow context
    logger.info("\n🎭 Testing with mocked workflow context...")
    
    # Mock workflow context
    mock_workflow_info = MagicMock()
    mock_workflow_info.workflow_id = "test-workflow-123"
    
    intercepted_calls = []
    
    def mock_activity_execution(activity_name, args, **kwargs):
        """Mock activity execution that tracks intercepted calls."""
        intercepted_calls.append({"activity": activity_name, "args": args})
        logger.info(f"   🎯 INTERCEPTED: {activity_name} with args: {args}")
        return {"intercepted": True, "activity": activity_name}
    
    # Import workflow module to patch it directly
    from temporalio import workflow as workflow_module
    
    with patch.object(workflow_module, 'info', return_value=mock_workflow_info), \
         patch.object(workflow_module, 'execute_activity', side_effect=mock_activity_execution):
        
        try:
            # This should call the interceptor, which should execute via Temporal
            result = await tool.run_async(args={"test": "with_workflow"}, tool_context=tool_context)
            logger.info(f"Tool result (with workflow): {result}")
        except Exception as e:
            logger.error(f"Tool call failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Analyze results
    logger.info(f"\n📊 RESULTS:")
    logger.info(f"✅ Methods patched: {tool_patched and llm_patched}")
    logger.info(f"✅ Intercepted calls: {len(intercepted_calls)}")
    
    for call in intercepted_calls:
        logger.info(f"   - {call['activity']}: {call['args']}")
    
    success = (tool_patched and llm_patched and len(intercepted_calls) > 0)
    
    if success:
        logger.info("\n🎉 SUCCESS! Interception is working!")
        logger.info("   • Methods successfully patched")
        logger.info("   • Interceptors called in workflow context")
        logger.info("   • Calls routed through Temporal activities")
    else:
        logger.error("\n❌ FAILED! Interception is not working properly")
    
    return success

if __name__ == "__main__":
    success = asyncio.run(test_simple_interception())
    exit(0 if success else 1)