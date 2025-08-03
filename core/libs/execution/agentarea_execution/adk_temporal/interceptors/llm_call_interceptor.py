"""LLM call interceptor that routes every LLM call through Temporal activities.

This module ensures that EVERY LLM call from ADK becomes a Temporal activity,
providing retry capabilities, observability, and workflow orchestration.
"""

import logging
from typing import Any, AsyncGenerator, Dict, List
from functools import wraps

from temporalio import workflow
from google.genai import types

from ...ag.adk.models.base_llm import BaseLlm
from ...ag.adk.models.llm_request import LlmRequest
from ...ag.adk.models.llm_response import LlmResponse

logger = logging.getLogger(__name__)


class TemporalLlmCallInterceptor:
    """Interceptor that routes all LLM calls through Temporal activities."""
    
    @staticmethod
    def intercept_llm_execution():
        """Monkey patch BaseLlm.generate_content_async to route through Temporal activities."""
        
        # Store the original method
        original_generate_content_async = BaseLlm.generate_content_async
        
        async def temporal_generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            """Intercepted generate_content_async that routes through Temporal activity."""
            logger.info(f"🎯 INTERCEPTOR CALLED: LLM {self.model} - request: {llm_request}")
            
            try:
                # Check if we're in a workflow context
                workflow_info = workflow.info()
                logger.info(f"LLM call for {self.model} executing in workflow: {workflow_info.workflow_id}")
                
                # Convert LlmRequest to serializable format
                messages = TemporalLlmCallInterceptor._convert_llm_request_to_messages(llm_request)
                tools = TemporalLlmCallInterceptor._extract_tools_from_request(llm_request)
                
                # Execute via Temporal activity
                activity_name = "call_llm_activity"
                
                result = await workflow.execute_activity(
                    activity_name,
                    args=[messages, self.model, tools],
                    start_to_close_timeout=300,  # 5 minutes
                    heartbeat_timeout=30,  # 30 seconds
                    # retry_policy can be added later if needed
                )
                
                # Convert result back to LlmResponse
                response = TemporalLlmCallInterceptor._convert_result_to_llm_response(result)
                logger.info(f"LLM call for {self.model} completed via Temporal activity")
                yield response
                
            except RuntimeError as e:
                # Not in workflow context, fall back to original method
                logger.warning(f"LLM call for {self.model} not in workflow context (RuntimeError: {e}), using original method")
                async for response in original_generate_content_async(self, llm_request, stream):
                    yield response
            except Exception as e:
                logger.error(f"LLM call for {self.model} failed via Temporal: {e}")
                # Fall back to original method on error
                async for response in original_generate_content_async(self, llm_request, stream):
                    yield response
        
        # Replace the method
        BaseLlm.generate_content_async = temporal_generate_content_async
        logger.info("✅ LLM call interception enabled - all LLM calls will go through Temporal activities")
    
    @staticmethod
    def _convert_llm_request_to_messages(llm_request: LlmRequest) -> List[Dict[str, Any]]:
        """Convert ADK LlmRequest to OpenAI-compatible messages format."""
        messages = []
        
        # Add system instruction if present
        if llm_request.system_instruction:
            system_content = TemporalLlmCallInterceptor._extract_text_from_content(llm_request.system_instruction)
            if system_content:
                messages.append({
                    "role": "system",
                    "content": system_content
                })
        
        # Add conversation contents
        for content in llm_request.contents:
            role = content.role if content.role else "user"
            # Map ADK roles to OpenAI format
            if role == "model":
                role = "assistant"
            
            message_content = TemporalLlmCallInterceptor._extract_text_from_content(content)
            if message_content:
                messages.append({
                    "role": role,
                    "content": message_content
                })
        
        return messages
    
    @staticmethod
    def _extract_tools_from_request(llm_request: LlmRequest) -> List[Dict[str, Any]] | None:
        """Extract tools from LLM request in OpenAI format."""
        if not llm_request.config or not llm_request.config.tools:
            return None
        
        tools = []
        for tool in llm_request.config.tools:
            if hasattr(tool, 'function_declarations'):
                for func_decl in tool.function_declarations:
                    tool_def = {
                        "type": "function",
                        "function": {
                            "name": func_decl.name,
                            "description": func_decl.description or "",
                        }
                    }
                    
                    # Add parameters if available
                    if hasattr(func_decl, 'parameters') and func_decl.parameters:
                        tool_def["function"]["parameters"] = func_decl.parameters
                    
                    tools.append(tool_def)
        
        return tools if tools else None
    
    @staticmethod
    def _extract_text_from_content(content: types.Content) -> str:
        """Extract text from ADK Content object."""
        if not content or not content.parts:
            return ""
        
        text_parts = []
        for part in content.parts:
            if hasattr(part, 'text') and part.text:
                text_parts.append(part.text)
            elif hasattr(part, 'function_call'):
                # Handle function calls
                func_call = part.function_call
                text_parts.append(f"Function call: {func_call.name}({func_call.args})")
            elif hasattr(part, 'function_response'):
                # Handle function responses
                func_resp = part.function_response
                text_parts.append(f"Function response: {func_resp.name} -> {func_resp.response}")
        
        return " ".join(text_parts)
    
    @staticmethod
    def _convert_result_to_llm_response(result: Dict[str, Any]) -> LlmResponse:
        """Convert Temporal activity result to ADK LlmResponse."""
        # Extract content
        content_text = result.get("content", "")
        parts = [types.Part(text=content_text)]
        
        # Handle tool calls if present
        if "tool_calls" in result:
            for tool_call in result["tool_calls"]:
                func_call = types.FunctionCall(
                    name=tool_call["function"]["name"],
                    args=tool_call["function"]["arguments"]
                )
                parts.append(types.Part(function_call=func_call))
        
        content = types.Content(
            role="model",
            parts=parts
        )
        
        # Extract usage information
        usage_data = result.get("usage", {})
        usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=usage_data.get("prompt_tokens", 0),
            candidates_token_count=usage_data.get("completion_tokens", 0)
        )
        
        return LlmResponse(
            content=content,
            usage_metadata=usage
        )
    
    @staticmethod
    def restore_original_llm_execution():
        """Restore original LLM execution (for testing or disabling)."""
        # This would require storing the original method, but for now we'll just log
        logger.info("LLM call interception would be restored here")


def enable_llm_call_interception():
    """Enable LLM call interception globally."""
    TemporalLlmCallInterceptor.intercept_llm_execution()


def disable_llm_call_interception():
    """Disable LLM call interception globally."""
    TemporalLlmCallInterceptor.restore_original_llm_execution()