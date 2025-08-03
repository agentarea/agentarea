"""Temporal-backed LLM service for ADK integration.

This service intercepts ADK LLM calls and routes them through Temporal activities,
making Temporal the backbone for LLM execution while keeping ADK untouched.
"""

import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import UUID

from google.genai import types
from temporalio import workflow

from ...ag.adk.models.base_llm import BaseLlm
from ...ag.adk.models.llm_request import LlmRequest
from ...ag.adk.models.llm_response import LlmResponse
from ..utils.event_serializer import EventSerializer

logger = logging.getLogger(__name__)


class TemporalLlmService(BaseLlm):
    """LLM service that routes calls through Temporal activities.
    
    This service acts as a bridge between ADK's LLM interface and Temporal
    workflow activities, enabling workflow orchestration of LLM calls.
    """
    
    # Define additional fields for Pydantic
    agent_config: Dict[str, Any]
    session_data: Dict[str, Any]
    
    def __init__(self, model: str, agent_config: Dict[str, Any], session_data: Dict[str, Any]):
        """Initialize the Temporal LLM service.
        
        Args:
            model: Model identifier (can be UUID or model name)
            agent_config: Agent configuration for context
            session_data: Session data for context
        """
        super().__init__(model=model, agent_config=agent_config, session_data=session_data)
        
    @classmethod
    def supported_models(cls) -> List[str]:
        """Return supported model patterns."""
        return [
            r".*",  # Support all models - delegate to Temporal activity
        ]
    
    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        """Generate content via Temporal activity.
        
        Args:
            llm_request: The LLM request to process
            stream: Whether to stream the response (not supported yet)
            
        Yields:
            LLM responses from Temporal activity execution
        """
        try:
            logger.info(f"Routing LLM call through Temporal for model: {self.model}")
            
            # Convert LlmRequest to serializable format
            messages = self._convert_llm_request_to_messages(llm_request)
            tools = self._extract_tools_from_request(llm_request)
            
            # Check if we're in a workflow or activity context
            # Use temporalio.activity to detect if we're in an activity
            try:
                from temporalio import activity
                activity.info()
                # If we get here, we're in an activity context
                is_in_activity = True
            except RuntimeError:
                # Not in activity context, might be in workflow context
                is_in_activity = False
            
            if is_in_activity:
                # We're in an activity context - call the LLM directly
                logger.info("Running in activity context - calling LLM directly")
                from ...activities.agent_execution_activities import call_llm_activity
                
                # Get the global reference to the activity function
                if call_llm_activity is None:
                    raise RuntimeError("call_llm_activity not available - activities not initialized")
                
                # Call the activity function directly (not through Temporal)
                result = await call_llm_activity(messages, self.model, tools)
            else:
                # We're in a workflow context - can call activities through Temporal
                from ...activities.agent_execution_activities import call_llm_activity
                
                result = await workflow.execute_activity(
                    call_llm_activity,
                    args=[messages, self.model, tools],
                    start_to_close_timeout=300,  # 5 minutes timeout
                    heartbeat_timeout=30,  # 30 seconds heartbeat
                )
            
            # Convert result back to LlmResponse
            response = self._convert_result_to_llm_response(result)
            yield response
            
        except Exception as e:
            logger.error(f"Temporal LLM call failed: {e}")
            # Return error response
            error_response = LlmResponse(
                content=types.Content(parts=[
                    types.Part(text=f"LLM call failed: {str(e)}")
                ]),
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=0,
                    candidates_token_count=0
                )
            )
            yield error_response
    
    def _convert_llm_request_to_messages(self, llm_request: LlmRequest) -> List[Dict[str, Any]]:
        """Convert ADK LlmRequest to OpenAI-compatible messages format.
        
        Args:
            llm_request: ADK LLM request
            
        Returns:
            List of message dictionaries
        """
        messages = []
        
        # Add system instruction if present
        if llm_request.config and llm_request.config.system_instruction:
            # system_instruction is already a string, no need to extract
            system_content = llm_request.config.system_instruction
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
            
            message_content = self._extract_text_from_content(content)
            if message_content:
                messages.append({
                    "role": role,
                    "content": message_content
                })
        
        return messages
    
    def _extract_tools_from_request(self, llm_request: LlmRequest) -> Optional[List[Dict[str, Any]]]:
        """Extract tools from LLM request in OpenAI format.
        
        Args:
            llm_request: ADK LLM request
            
        Returns:
            List of tool definitions or None
        """
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
    
    def _extract_text_from_content(self, content: types.Content) -> str:
        """Extract text from ADK Content object.
        
        Args:
            content: ADK Content object
            
        Returns:
            Extracted text content
        """
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
    
    def _convert_result_to_llm_response(self, result: Dict[str, Any]) -> LlmResponse:
        """Convert Temporal activity result to ADK LlmResponse.
        
        Args:
            result: Result from Temporal LLM activity
            
        Returns:
            ADK LlmResponse object
        """
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


class TemporalLlmServiceFactory:
    """Factory for creating Temporal-backed LLM services."""
    
    @staticmethod
    def create_llm_service(
        model: str, 
        agent_config: Dict[str, Any], 
        session_data: Dict[str, Any]
    ) -> TemporalLlmService:
        """Create a Temporal LLM service.
        
        Args:
            model: Model identifier
            agent_config: Agent configuration
            session_data: Session data
            
        Returns:
            Configured TemporalLlmService
        """
        return TemporalLlmService(
            model=model,
            agent_config=agent_config,
            session_data=session_data
        )
    
    @staticmethod
    def register_with_adk():
        """Register Temporal LLM service with ADK's LLM registry."""
        try:
            from ...ag.adk.models.registry import LLMRegistry
            
            # Register our service to handle all models
            LLMRegistry.register(TemporalLlmService)
            logger.info("Registered TemporalLlmService with ADK LLM registry")
            
        except Exception as e:
            logger.error(f"Failed to register TemporalLlmService: {e}")