"""
Temporal Flow for Google ADK Integration

Clean implementation that extends BaseLlmFlow to route LLM calls
through Temporal activities while preserving all ADK functionality.
"""

import logging
from typing import AsyncGenerator, Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Handle Google ADK imports gracefully
try:
    from google.adk.flows.llm_flows.base_llm_flow import BaseLlmFlow
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.models.llm_request import LlmRequest
    from google.adk.models.llm_response import LlmResponse
    from google.adk.events.event import Event
    ADK_AVAILABLE = True
except ImportError:
    logger.warning("Google ADK not available - using stubs")
    class BaseLlmFlow: 
        def __init__(self): 
            self.request_processors = []
            self.response_processors = []
    class InvocationContext: pass
    class LlmRequest: pass
    class LlmResponse: pass
    class Event: pass
    ADK_AVAILABLE = False

from .interfaces import ActivityServicesInterface


class TemporalFlow(BaseLlmFlow):
    """Custom ADK flow that routes LLM calls through Temporal activities.
    
    This is the core innovation - we extend BaseLlmFlow and override just
    the _call_llm_async method to route through Temporal activities.
    """

    def __init__(self, activity_services: ActivityServicesInterface, agent_id: UUID):
        super().__init__()
        self.activity_services = activity_services
        self.agent_id = agent_id
        
        # Only set up processors if ADK is available
        if ADK_AVAILABLE:
            self._setup_adk_processors()

    def _setup_adk_processors(self):
        """Set up ADK processors - only called if ADK is available."""
        try:
            from google.adk.flows.llm_flows import (
                basic, instructions, identity, contents,
                _nl_planning, _code_execution
            )
            
            # Use the same processors as SingleFlow for compatibility
            self.request_processors += [
                basic.request_processor,
                instructions.request_processor,
                identity.request_processor,
                contents.request_processor,
                _nl_planning.request_processor,
                _code_execution.request_processor,
            ]
            self.response_processors += [
                _nl_planning.response_processor,
                _code_execution.response_processor,
            ]
        except ImportError:
            logger.warning("Some ADK processors not available")

    async def _call_llm_async(
        self,
        invocation_context: InvocationContext,
        llm_request: LlmRequest,
        model_response_event: Event,
    ) -> AsyncGenerator[LlmResponse, None]:
        """
        This is the key override - route LLM calls through Temporal activities.
        
        Uses dynamic configuration building for:
        - Different LLMs per execution step
        - Context-aware configuration
        - Future-proof evolution
        """
        try:
            logger.info("TemporalFlow: Routing LLM call through Temporal activity with dynamic config")
            
            # Convert ADK LlmRequest to simple format for Temporal activity
            messages = self._extract_messages_from_llm_request(llm_request)
            
            # Build execution context from current state
            execution_context = self._build_execution_context(invocation_context, messages)
            
            # Determine step type based on context (can be overridden by invocation context)
            step_type = self._determine_step_type(execution_context, invocation_context)
            
            # Build dynamic agent configuration via activity
            config_result = await self._build_dynamic_config_via_activity(
                execution_context=execution_context,
                step_type=step_type
            )
            
            if not config_result.get("success", False):
                raise ValueError(f"Failed to build dynamic config: {config_result.get('error')}")
            
            agent_config = config_result["config"]
            logger.info(f"Using dynamic config for step: {step_type}, model: {agent_config.get('model_override', 'default')}")
            
            # Discover available tools through activity
            available_tools = await self._discover_tools_via_activity()
            
            # Call our Temporal activity for LLM execution
            llm_result = await self._call_llm_activity(
                messages=messages,
                agent_config=agent_config,
                available_tools=available_tools
            )
            
            # Convert result back to ADK LlmResponse format
            llm_response = self._create_llm_response_from_result(llm_result)
            
            yield llm_response
            
        except Exception as e:
            logger.error(f"TemporalFlow LLM call failed: {e}")
            # Create error response
            yield self._create_error_response("temporal_execution_error")
    
    def _build_execution_context(self, invocation_context: InvocationContext, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build execution context from current invocation state."""
        context = {
            "messages_count": len(messages),
            "last_message_length": len(messages[-1]["content"]) if messages else 0,
        }
        
        # Extract task complexity hints from messages
        if messages:
            last_message = messages[-1]["content"].lower()
            if any(word in last_message for word in ["code", "programming", "function", "implement"]):
                context["task_type"] = "coding"
                context["complexity"] = "high"
                context["expected_response_length"] = "long"
            elif any(word in last_message for word in ["analyze", "explain", "reason", "think"]):
                context["task_type"] = "analytical"
                context["complexity"] = "high"
                context["expected_response_length"] = "medium"
            elif any(word in last_message for word in ["creative", "story", "write", "generate"]):
                context["task_type"] = "creative"
                context["complexity"] = "medium"
                context["expected_response_length"] = "long"
            else:
                context["task_type"] = "general"
                context["complexity"] = "medium"
                context["expected_response_length"] = "medium"
        
        # Add invocation-specific context if available
        if hasattr(invocation_context, 'branch') and invocation_context.branch:
            context["execution_branch"] = invocation_context.branch
        
        return context
    
    def _determine_step_type(self, execution_context: Dict[str, Any], invocation_context: InvocationContext) -> str:
        """Determine the type of execution step for optimal model selection."""
        
        # Check if step type is explicitly provided in context
        if hasattr(invocation_context, 'step_type'):
            return getattr(invocation_context, 'step_type')
        
        # Infer step type from context
        task_type = execution_context.get("task_type", "general")
        messages_count = execution_context.get("messages_count", 0)
        
        if messages_count <= 2:
            return "initial_parsing"
        elif task_type == "coding":
            return "coding"
        elif task_type == "analytical":
            return "analysis"
        elif task_type == "creative":
            return "reasoning"
        else:
            return "reasoning"
    
    async def _build_dynamic_config_via_activity(
        self, 
        execution_context: Dict[str, Any],
        step_type: str,
        override_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build dynamic agent configuration via Temporal activity."""
        # Import here to avoid circular imports
        from .activities.agent_activities import build_agent_config_activity
        
        return await build_agent_config_activity(
            agent_id=self.agent_id,
            activity_services=self.activity_services,
            execution_context=execution_context,
            step_type=step_type,
            override_model=override_model,
        )

    def _extract_messages_from_llm_request(self, llm_request: LlmRequest) -> List[Dict[str, Any]]:
        """Extract messages from ADK LlmRequest."""
        messages = []
        
        if hasattr(llm_request, 'contents') and llm_request.contents:
            for content in llm_request.contents:
                if hasattr(content, 'role') and hasattr(content, 'parts'):
                    if content.role and content.parts:
                        text_parts = []
                        for part in content.parts:
                            if hasattr(part, 'text') and part.text:
                                text_parts.append(part.text)
                        
                        if text_parts:
                            messages.append({
                                "role": content.role,
                                "content": " ".join(text_parts)
                            })
        
        return messages

    async def _call_llm_activity(
        self, 
        messages: List[Dict[str, Any]], 
        agent_config: Dict[str, Any],
        available_tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Call the Temporal activity for LLM execution."""
        # Import here to avoid circular imports
        from .activities.agent_activities import call_llm_activity
        
        return await call_llm_activity(
            messages=messages,
            model_config=agent_config,
            available_tools=available_tools,
            activity_services=self.activity_services,
        )

    async def _discover_tools_via_activity(self) -> List[Dict[str, Any]]:
        """Discover available tools via Temporal activity."""
        # Import here to avoid circular imports
        from .activities.agent_activities import discover_available_tools_activity
        
        return await discover_available_tools_activity(
            agent_id=self.agent_id,
            activity_services=self.activity_services,
        )

    def _create_llm_response_from_result(self, activity_result: Dict[str, Any]) -> LlmResponse:
        """Convert Temporal activity result back to ADK LlmResponse."""
        if not ADK_AVAILABLE:
            return LlmResponse()
        
        if not activity_result.get("success", False):
            return self._create_error_response("llm_execution_error")
        
        try:
            from google.genai import types
            
            # Create content from activity result
            response_text = activity_result.get("response_text", "")
            content = types.Content(
                role="model",
                parts=[types.Part(text=response_text)]
            )
            
            # Handle tool calls if present (future enhancement)
            tool_calls = activity_result.get("tool_calls", [])
            if tool_calls:
                for tool_call in tool_calls:
                    function_call = types.Part(
                        function_call=types.FunctionCall(
                            name=tool_call.get("name", "unknown"),
                            args=tool_call.get("arguments", {})
                        )
                    )
                    content.parts.append(function_call)
            
            return LlmResponse(
                content=content,
                error_code=None,
                interrupted=False,
                turn_complete=activity_result.get("finish_reason") != "continue"
            )
            
        except ImportError:
            logger.warning("Google genai types not available")
            return self._create_error_response("import_error")

    def _create_error_response(self, error_code: str) -> LlmResponse:
        """Create an error response."""
        return LlmResponse(
            content=None,
            error_code=error_code,
            interrupted=False
        ) 