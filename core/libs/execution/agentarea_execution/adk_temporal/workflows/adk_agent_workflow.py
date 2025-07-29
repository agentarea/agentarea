"""ADK-Temporal Workflow Implementation."""

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional
import time

from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta

from ...models import AgentExecutionRequest, AgentExecutionResult
from ..activities.adk_agent_activities import (
    validate_agent_configuration,
    create_agent_runner,
    execute_agent_step,
    stream_adk_agent_activity,
)
from ..utils.event_serializer import EventSerializer
from ..utils.agent_builder import create_simple_agent_config

logger = logging.getLogger(__name__)


@workflow.defn
class ADKAgentWorkflow:
    
    # Workflow version for backward compatibility
    VERSION = "1.0.0"

    def __init__(self):
        self._logger = logging.getLogger(__name__).getChild(self.__class__.__name__)
        
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
        self.start_time = time.time()
        
        try:
            self._logger.info(f"Starting ADK agent workflow for task: {request.task_id}")

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
            
            self._logger.info(
                f"Initialized workflow for agent: {self.agent_config.get('name', 'unknown')}"
            )

            await self._validate_configuration()

            await workflow.execute_activity(
                create_agent_runner,
                args=[self.agent_config, self.session_data],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=10),
                    maximum_attempts=3,
                ),
            )
    
            result = await self._execute_granular_agent()

            return await self._finalize_execution(result)

        except Exception as e:
            self._logger.error(f"ADK agent workflow failed: {str(e)}")
            await self._handle_workflow_error(e)
            raise
        finally:
            self.end_time = time.time()
            self._log_metrics()

    async def _initialize_workflow(self, request: AgentExecutionRequest) -> None:
        self._logger.info("Initializing ADK agent workflow")

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

        self._logger.info(
            f"Initialized workflow for agent: {self.agent_config.get('name', 'unknown')}"
        )

    async def _build_agent_config(self, request: AgentExecutionRequest) -> Dict[str, Any]:
        agent_config = create_simple_agent_config(
            name=f"agent_{request.agent_id}",
            model="gpt-4",
            instructions=f"You are an AI assistant helping with task: {request.task_query}",
            description="AgentArea AI assistant",
        )

        if hasattr(request, "task_parameters") and request.task_parameters:
            agent_config.update(request.task_parameters)

        return agent_config

    async def _validate_configuration(self) -> None:
        self._logger.info("Validating ADK agent configuration")

        try:
            await workflow.execute_activity(
                validate_agent_configuration,
                args=[self.agent_config],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=10),
                    maximum_attempts=3,
                ),
            )

            self._logger.info("Agent configuration validated successfully")

        except Exception as e:
            self._logger.error(f"Configuration validation failed: {e}")
            raise

    async def _execute_granular_agent(self) -> Dict[str, Any]:
        self._logger.info("Executing ADK agent with granular activities")
        history = []  # Maintain conversation history
        final_response = None
        while True:
            # Prepare LLM request based on history and user message
            llm_request = self._prepare_llm_request(history, self.user_message)
            # Execute LLM activity
            llm_response = await workflow.execute_activity(
                execute_llm_call,
                args=[self.agent_config, self.session_data, llm_request],
                start_to_close_timeout=timedelta(minutes=5),
            )
            history.append(llm_response)
            self.events.append(llm_response)
            # Check if response has tool calls
            tool_calls = self._extract_tool_calls(llm_response)
            if tool_calls:
                for tool_call in tool_calls:
                    tool_result = await workflow.execute_activity(
                        execute_tool_call,
                        args=[self.agent_config, self.session_data, tool_call],
                        start_to_close_timeout=timedelta(minutes=5),
                    )
                    history.append(tool_result)
                    self.events.append(tool_result)
            else:
                final_response = self._extract_final_response([llm_response])
                if final_response:
                    break
        self.success = True
        return {
            "event_count": len(self.events),
            "final_response": final_response,
            "success": self.success,
        }

            return await self._finalize_execution(result)

        except Exception as e:
            self._logger.error(f"ADK agent workflow failed: {str(e)}")
            await self._handle_workflow_error(e)
            raise
        finally:
            self.end_time = time.time()
            self._log_metrics()

    async def _execute_adk_agent(self) -> Dict[str, Any]:
        self._logger.info("Starting ADK agent execution")

        try:
            use_streaming = self._should_use_streaming()

            if use_streaming:
                return await self._execute_streaming_agent()
            else:
                return await self._execute_batch_agent()

        except Exception as e:
            self._logger.error(f"ADK agent execution failed: {e}")
            self.error_message = str(e)
            raise

    def _should_use_streaming(self) -> bool:
        # Enable streaming based on task parameters
        return self.agent_config.get("enable_streaming", False)

    async def _execute_batch_agent(self) -> Dict[str, Any]:
        self._logger.info("Executing ADK agent in batch mode")

        events = await workflow.execute_activity(
            execute_agent_step,
            args=[
                self.agent_config,
                self.session_data,
                self.user_message,
                None,
            ],
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=5,
            ),
        )

        self.events = events

        final_response = self._extract_final_response(events)
        if final_response:
            self.final_response = final_response
            self.success = True

        self._logger.info(f"Batch execution completed with {len(events)} events")

        return {
            "event_count": len(events),
            "final_response": final_response,
            "success": self.success,
        }

    async def _execute_streaming_agent(self) -> Dict[str, Any]:
        self._logger.info("Executing ADK agent in streaming mode")

        event_count = 0

        handle = await workflow.start_activity(
            stream_adk_agent_activity,
            args=[self.agent_config, self.session_data, self.user_message, None],
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=5,
            ),
        )
        async for event_dict in handle:
            event_count += 1
            self.events.append(event_dict)

            if self.paused:
                self._logger.info(
                    f"Execution paused after {event_count} events: {self.pause_reason}"
                )
                await workflow.wait_condition(lambda: not self.paused)
                self._logger.info("Execution resumed")

            if self._is_final_event(event_dict):
                final_response = EventSerializer.extract_final_response(
                    EventSerializer.dict_to_event(event_dict)
                )
                if final_response:
                    self.final_response = final_response
                    self.success = True
                break

        self._logger.info(f"Streaming execution completed with {event_count} events")

        return {
            "event_count": event_count,
            "final_response": self.final_response,
            "success": self.success,
        }

    async def _prepare_llm_request(self, history: List[Dict[str, Any]], user_message: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare LLM request from history and user message."""
        request = {
            'contents': history + [user_message],
            'system_instruction': self.agent_config.get('instructions', ''),
            'tools': self.agent_config.get('tools', []),
            'generation_config': self.agent_config.get('generate_content_config', {})
        }
        return request

    def _extract_tool_calls(self, llm_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract tool calls from LLM response."""
        # Assuming llm_response has 'candidates' with tool calls
        candidates = llm_response.get('candidates', [])
        if candidates and 'content' in candidates[0] and 'parts' in candidates[0]['content']:
            parts = candidates[0]['content']['parts']
            tool_calls = [part for part in parts if 'function_call' in part]
            return [{'name': tc['function_call']['name'], 'args': tc['function_call']['args']} for tc in tool_calls]
        return []

    def _extract_final_response(self, llm_responses: List[Dict[str, Any]]) -> Optional[str]:
        """Extract final response from LLM responses."""
        # Simple extraction, assuming last response's text
        if llm_responses:
            last = llm_responses[-1]
            candidates = last.get('candidates', [])
            if candidates and 'content' in candidates[0] and 'parts' in candidates[0]['content']:
                parts = candidates[0]['content']['parts']
                text_parts = [part['text'] for part in parts if 'text' in part]
                return ''.join(text_parts)
        return None

    def _is_final_event(self, event_dict: Dict[str, Any]) -> bool:
        try:
            event = EventSerializer.dict_to_event(event_dict)
            return event.is_final_response()
        except Exception:
            return False

    def _calculate_total_cost(self, events: List[Dict[str, Any]]) -> float:
        total_cost = 0.0
        for event_dict in events:
            try:
                if "cost" in event_dict:
                    total_cost += event_dict["cost"]
            except Exception as e:
                self._logger.warning(f"Failed to calculate cost for event: {e}")
        return total_cost

    async def _finalize_execution(self, result: Dict[str, Any]) -> AgentExecutionResult:
        self._logger.info("Finalizing ADK agent workflow execution")

        conversation_history = []
        for event_dict in self.events:
            try:
                event = EventSerializer.dict_to_event(event_dict)
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            conversation_history.append(
                                {
                                    "role": event.author,
                                    "content": part.text,
                                    "timestamp": event.timestamp,
                                }
                            )
            except Exception as e:
                self._logger.warning(f"Failed to convert event to history: {e}")

        from uuid import UUID

        execution_result = AgentExecutionResult(
            task_id=UUID(self.session_data["state"]["task_id"]),
            agent_id=UUID(self.session_data["state"]["agent_id"]),
            success=self.success,
            final_response=self.final_response or "No final response generated",
            total_cost=0.0,
            reasoning_iterations_used=len(self.events),
            conversation_history=conversation_history,
        )

        self._logger.info(
            f"Workflow completed - Success: {self.success}, Events: {len(self.events)}"
        )
        
        self.event_count = len(self.events)
        self.total_cost = self._calculate_total_cost(self.events)
        
        return execution_result

    async def _handle_workflow_error(self, error: Exception) -> None:
        self.error_message = str(error)
        self.success = False

        self._logger.error(f"Workflow error handled: {error}")

    def _log_metrics(self) -> None:
        execution_time = self.end_time - self.start_time if self.end_time > 0 else 0
        self._logger.info(
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
        self._logger.info(f"Workflow paused: {reason}")

    @workflow.signal
    async def resume(self, reason: str = "Manual resume") -> None:
        self.paused = False
        self.pause_reason = ""
        self._logger.info(f"Workflow resumed: {reason}")

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
