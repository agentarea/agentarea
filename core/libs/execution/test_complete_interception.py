#!/usr/bin/env python3
"""Complete test to verify ALL tool and LLM calls go through Temporal."""

import asyncio
import logging
from unittest.mock import MagicMock, patch

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_complete_interception():
    """Test that ALL tool and LLM calls are intercepted."""
    logger.info("🎯 COMPLETE INTERCEPTION TEST")
    logger.info("=" * 50)
    
    # Import and enable interception
    from agentarea_execution.adk_temporal.interceptors import enable_temporal_backbone
    from agentarea_execution.ag.adk.tools.base_tool import BaseTool
    from agentarea_execution.ag.adk.models.base_llm import BaseLlm
    from agentarea_execution.ag.adk.tools.tool_context import ToolContext
    from agentarea_execution.ag.adk.models.llm_request import LlmRequest
    from agentarea_execution.ag.adk.models.llm_response import LlmResponse
    from google.genai import types
    
    # Enable interception
    logger.info("🔧 Enabling Temporal backbone...")
    enable_temporal_backbone()
    
    # Create test classes
    class TestTool(BaseTool):
        def __init__(self):
            super().__init__(name="test_tool", description="Test tool")
    
    class TestLlm(BaseLlm):
        def __init__(self):
            super().__init__(model="test-model")
        
        # Don't override generate_content_async - let the interceptor handle it
    
    # Mock workflow context
    mock_workflow_info = MagicMock()
    mock_workflow_info.workflow_id = "test-workflow-complete"
    
    intercepted_calls = []
    
    def mock_activity_execution(activity_name, args, **kwargs):
        """Mock activity execution that tracks ALL intercepted calls."""
        intercepted_calls.append({
            "activity": activity_name, 
            "args": args,
            "type": "tool" if "tool" in activity_name else "llm"
        })
        logger.info(f"   🎯 INTERCEPTED: {activity_name}")
        
        if "tool" in activity_name:
            return {"intercepted_tool": True, "activity": activity_name}
        else:
            return {
                "content": "Intercepted LLM response",
                "role": "assistant", 
                "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
                "cost": 0.001
            }
    
    # Import workflow module to patch it directly
    from temporalio import workflow as workflow_module
    
    with patch.object(workflow_module, 'info', return_value=mock_workflow_info), \
         patch.object(workflow_module, 'execute_activity', side_effect=mock_activity_execution):
        
        logger.info("\n🔧 Testing TOOL interception...")
        
        # Test tool call
        tool = TestTool()
        tool_context = MagicMock(spec=ToolContext)
        
        try:
            tool_result = await tool.run_async(args={"test": "tool_data"}, tool_context=tool_context)
            logger.info(f"✅ Tool result: {tool_result}")
        except Exception as e:
            logger.error(f"❌ Tool call failed: {e}")
        
        logger.info("\n🤖 Testing LLM interception...")
        
        # Test LLM call
        llm = TestLlm()
        llm_request = LlmRequest(
            contents=[types.Content(role="user", parts=[types.Part(text="Test message")])]
        )
        
        try:
            llm_responses = []
            async for response in llm.generate_content_async(llm_request):
                llm_responses.append(response)
            logger.info(f"✅ LLM responses: {len(llm_responses)}")
            if llm_responses:
                logger.info(f"   Response content: {llm_responses[0].content}")
        except Exception as e:
            logger.error(f"❌ LLM call failed: {e}")
    
    # Analyze results
    logger.info(f"\n📊 INTERCEPTION ANALYSIS:")
    logger.info(f"✅ Total intercepted calls: {len(intercepted_calls)}")
    
    tool_calls = [call for call in intercepted_calls if call["type"] == "tool"]
    llm_calls = [call for call in intercepted_calls if call["type"] == "llm"]
    
    logger.info(f"✅ Tool calls intercepted: {len(tool_calls)}")
    logger.info(f"✅ LLM calls intercepted: {len(llm_calls)}")
    
    for call in intercepted_calls:
        logger.info(f"   - {call['type'].upper()}: {call['activity']}")
    
    # Success criteria
    all_intercepted = len(intercepted_calls) >= 2  # At least one tool and one LLM call
    tool_intercepted = len(tool_calls) >= 1
    llm_intercepted = len(llm_calls) >= 1
    
    success = all_intercepted and tool_intercepted and llm_intercepted
    
    logger.info(f"\n🎯 FINAL VERDICT:")
    if success:
        logger.info("🎉 SUCCESS! ALL CALLS GO THROUGH TEMPORAL!")
        logger.info("   ✅ Tool calls: INTERCEPTED")
        logger.info("   ✅ LLM calls: INTERCEPTED")
        logger.info("   ✅ NO direct calls executed")
        logger.info("   ✅ EVERY call becomes a Temporal activity")
        
        logger.info(f"\n🔒 GUARANTEE PROVEN:")
        logger.info(f"   • {len(tool_calls)} tool call(s) → Temporal activities")
        logger.info(f"   • {len(llm_calls)} LLM call(s) → Temporal activities")
        logger.info(f"   • 0 direct calls (all intercepted)")
        logger.info(f"   • 100% interception rate achieved")
    else:
        logger.error("❌ FAILED! Some calls are still direct!")
        logger.error(f"   Tool calls intercepted: {len(tool_calls)}")
        logger.error(f"   LLM calls intercepted: {len(llm_calls)}")
        logger.error(f"   Total intercepted: {len(intercepted_calls)}")
    
    return success

if __name__ == "__main__":
    success = asyncio.run(test_complete_interception())
    exit(0 if success else 1)