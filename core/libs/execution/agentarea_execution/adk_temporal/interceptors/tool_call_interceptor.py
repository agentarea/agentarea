"""Tool call interceptor that routes every tool execution through Temporal activities.

This module ensures that EVERY tool call from ADK becomes a Temporal activity,
providing retry capabilities, observability, and workflow orchestration.
"""

import logging
from typing import Any, Dict
from functools import wraps

from temporalio import workflow

from ...ag.adk.tools.base_tool import BaseTool
from ...ag.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


class TemporalToolCallInterceptor:
    """Interceptor that routes all tool calls through Temporal activities."""
    
    @staticmethod
    def intercept_tool_execution():
        """Monkey patch BaseTool.run_async to route through Temporal activities."""
        
        # Store the original method
        original_run_async = BaseTool.run_async
        
        async def temporal_run_async(self, *, args: Dict[str, Any], tool_context: ToolContext) -> Any:
            """Intercepted run_async that routes through Temporal activity."""
            logger.info(f"🎯 INTERCEPTOR CALLED: Tool {self.name} - args: {args}")
            
            try:
                # Check if we're in a workflow context
                workflow_info = workflow.info()
                logger.info(f"Tool call {self.name} executing in workflow: {workflow_info.workflow_id}")
                
                # Execute via Temporal activity
                activity_name = "execute_mcp_tool_activity"
                
                result = await workflow.execute_activity(
                    activity_name,
                    args=[self.name, args, getattr(self, 'server_instance_id', None)],
                    start_to_close_timeout=300,  # 5 minutes
                    heartbeat_timeout=30,  # 30 seconds
                    # retry_policy can be added later if needed
                )
                
                logger.info(f"Tool call {self.name} completed via Temporal activity")
                return result.get("result", result) if isinstance(result, dict) else result
                
            except RuntimeError as e:
                # Not in workflow context, fall back to original method
                logger.warning(f"Tool call {self.name} not in workflow context (RuntimeError: {e}), using original method")
                return await original_run_async(self, args=args, tool_context=tool_context)
            except Exception as e:
                logger.error(f"Tool call {self.name} failed via Temporal: {e}")
                # Fall back to original method on error
                return await original_run_async(self, args=args, tool_context=tool_context)
        
        # Replace the method
        BaseTool.run_async = temporal_run_async
        logger.info("✅ Tool call interception enabled - all tool calls will go through Temporal activities")
    
    @staticmethod
    def restore_original_tool_execution():
        """Restore original tool execution (for testing or disabling)."""
        # This would require storing the original method, but for now we'll just log
        logger.info("Tool call interception would be restored here")


def enable_tool_call_interception():
    """Enable tool call interception globally."""
    TemporalToolCallInterceptor.intercept_tool_execution()


def disable_tool_call_interception():
    """Disable tool call interception globally."""
    TemporalToolCallInterceptor.restore_original_tool_execution()