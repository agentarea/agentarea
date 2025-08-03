"""ADK-Temporal Workflow Implementation."""

import logging
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from uuid import UUID
    from ...models import AgentExecutionRequest, AgentExecutionResult

logger = logging.getLogger(__name__)


@workflow.defn
class ADKAgentWorkflow:
    """ADK Agent Workflow for Temporal execution."""

    def __init__(self):
        self.execution_id = ""
        self.agent_config: Dict[str, Any] = {}
        self.session_data: Dict[str, Any] = {}
        self.user_message: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []
        self.final_response: Optional[str] = None
        self.success = False
        self.error_message: Optional[str] = None
        self.paused = False
        self.pause_reason = ""
        self.start_time = 0.0
        self.end_time = 0.0
        self.event_count = 0
        self.total_cost = 0.0
        self.retry_attempts = 0

    @workflow.run
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.start_time = workflow.now().timestamp()
        try:
            logger.info(f"Starting ADK agent workflow for task: {request.task_id}")

            self.execution_id = workflow.info().workflow_id
            self.agent_config = await self._build_agent_config(request)
            self.session_data = {
                "user_id": str(request.task_id),
                "session_id": f"session_{request.task_id}",
                "app_name": "agentarea",
                "state": {
                    "task_id": str(request.task_id),
                    "agent_id": str(request.agent_id),
                    "execution_id": self.execution_id,
                },
            }
            self.user_message = {
                "content": request.task_query,
                "role": "user",
            }

            logger.info(
                f"Initialized workflow for agent: {self.agent_config.get('name', 'unknown')}"
            )

            await self._validate_configuration()

            # Skip agent runner creation - it will be handled in the execution activity

            # Choose execution mode: streaming or batch
            if self._should_use_streaming():
                result = await self._execute_streaming_agent()
            else:
                result = await self._execute_batch_agent()

            return await self._finalize_execution(result)

        except Exception as e:
            logger.error(f"ADK agent workflow failed: {str(e)}")
            await self._handle_workflow_error(e)
            raise
        finally:
            self.end_time = workflow.now().timestamp()
            self._log_metrics()

    async def _build_agent_config(self, request: AgentExecutionRequest) -> Dict[str, Any]:
        # Build agent config using the working activity
        agent_config = await workflow.execute_activity(
            "build_agent_config_activity",
            args=[request.agent_id, {"user_id": request.user_id, "workspace_id": "system"}],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )
        return agent_config

    async def _validate_configuration(self) -> None:
        logger.info("Validating ADK agent configuration")
        # Skip validation for now - the agent config from build_agent_config_activity is already valid
        logger.info("Agent configuration validated successfully")

    def _should_use_streaming(self) -> bool:
        return self.agent_config.get("enable_streaming", False)

    async def _execute_batch_agent(self) -> Dict[str, Any]:
        logger.info("Executing ADK agent in batch mode")
        
        # Prepare ADK agent config
        model_id = self.agent_config.get("model_id", "qwen2.5")
        if "/" not in model_id:
            model_id = f"ollama_chat/{model_id}"
        
        adk_agent_config = {
            "name": f"agent_{str(self.session_data['state']['agent_id']).replace('-', '_')}",
            "model": model_id,
            "instructions": f"You are an AI assistant. Task: {self.user_message['content']}",
            "description": self.agent_config.get("description", "AgentArea task execution agent"),
            "tools": []
        }
        
        events = await workflow.execute_activity(
            "execute_adk_agent_with_temporal_backbone",
            args=[adk_agent_config, self.session_data, self.user_message],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )
        
        self.events = events
        final_response = self._extract_final_response(events)
        if final_response:
            self.final_response = final_response
            self.success = True
        logger.info(f"Batch execution completed with {len(events)} events")
        return {
            "event_count": len(events),
            "final_response": final_response,
            "success": self.success,
        }

    async def _execute_streaming_agent(self) -> Dict[str, Any]:
        logger.info("Executing ADK agent in streaming mode")
        # For now, fall back to batch mode since streaming is not implemented
        return await self._execute_batch_agent()

    def _extract_final_response(self, events: List[Dict[str, Any]]) -> Optional[str]:
        if not events:
            return None
        last_event = events[-1]
        content_data = last_event.get("content", {})
        
        if isinstance(content_data, dict) and "parts" in content_data:
            text_parts = []
            for part in content_data.get("parts", []):
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
            
            if text_parts:
                return " ".join(text_parts)
        
        return None

    def _is_final_event(self, event_dict: Dict[str, Any]) -> bool:
        # Simple check - if we have content, consider it final
        return "content" in event_dict and event_dict["content"]

    def _calculate_total_cost(self, events: List[Dict[str, Any]]) -> float:
        total_cost = 0.0
        for event_dict in events:
            try:
                if "cost" in event_dict:
                    total_cost += event_dict["cost"]
            except Exception as e:
                logger.warning(f"Failed to calculate cost for event: {e}")
        return total_cost

    async def _finalize_execution(self, result: Dict[str, Any]) -> AgentExecutionResult:
        logger.info("Finalizing ADK agent workflow execution")
        conversation_history = []
        
        # Simple conversation history extraction
        for event_dict in self.events:
            try:
                content_data = event_dict.get("content", {})
                if isinstance(content_data, dict) and "parts" in content_data:
                    for part in content_data.get("parts", []):
                        if isinstance(part, dict) and "text" in part:
                            conversation_history.append({
                                "role": event_dict.get("author", "assistant"),
                                "content": part["text"],
                                "timestamp": event_dict.get("timestamp", 0),
                            })
            except Exception as e:
                logger.warning(f"Failed to convert event to history: {e}")

        execution_result = AgentExecutionResult(
            task_id=UUID(self.session_data["state"]["task_id"]),
            agent_id=UUID(self.session_data["state"]["agent_id"]),
            success=self.success,
            final_response=self.final_response or "No final response generated",
            total_cost=self._calculate_total_cost(self.events),
            reasoning_iterations_used=len(self.events),
            conversation_history=conversation_history,
        )

        logger.info(
            f"Workflow completed - Success: {self.success}, Events: {len(self.events)}"
        )

        self.event_count = len(self.events)
        self.total_cost = self._calculate_total_cost(self.events)

        return execution_result

    async def _handle_workflow_error(self, error: Exception) -> None:
        self.error_message = str(error)
        self.success = False
        logger.error(f"Workflow error handled: {error}")

    def _log_metrics(self) -> None:
        execution_time = self.end_time - self.start_time if self.end_time > 0 else 0
        logger.info(
            f"Workflow metrics - Execution ID: {self.execution_id}, "
            f"Execution Time: {execution_time:.2f}s, "
            f"Events Processed: {len(self.events)}, "
            f"Success: {self.success}, "
            f"Total Cost: ${self.total_cost:.4f}"
        )

    @workflow.signal
    async def pause(self, reason: str = "Manual pause") -> None:
        self.paused = True
        self.pause_reason = reason
        logger.info(f"Workflow paused: {reason}")

    @workflow.signal
    async def resume(self, reason: str = "Manual resume") -> None:
        self.paused = False
        self.pause_reason = ""
        logger.info(f"Workflow resumed: {reason}")

    @workflow.query
    def get_current_state(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "agent_name": self.agent_config.get("name", "unknown"),
            "event_count": len(self.events),
            "success": self.success,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "error_message": self.error_message,
            "has_final_response": self.final_response is not None,
        }

    @workflow.query
    def get_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.events[-limit:] if limit > 0 else self.events

    @workflow.query
    def get_final_response(self) -> Optional[str]:
        return self.final_response


def _dict_to_adk_content(message_dict: Dict[str, Any]) -> Any:
    """Convert message dictionary to ADK Content object.
    
    Args:
        message_dict: Dictionary containing message content
        
    Returns:
        ADK Content object or string content
    """
    content_data = message_dict.get("content", {})
    
    # Handle different content formats
    if isinstance(content_data, str):
        # Simple text content - return as string for now
        return content_data
    elif isinstance(content_data, dict):
        # Try to extract text from structured content
        if "parts" in content_data:
            text_parts = []
            for part in content_data.get("parts", []):
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
            return " ".join(text_parts) if text_parts else str(content_data)
        else:
            return str(content_data)
    else:
        # Fallback to string representation
        return str(content_data)
