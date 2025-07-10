"""
Agent execution workflow for AgentArea.

Simplified workflow that orchestrates agent execution activities.
The complex reasoning logic is delegated to activities, following Temporal best practices.
"""

import logging
from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow
from temporalio.common import RetryPolicy

from ..activities.agent_activities import (
    validate_agent_configuration_activity,
    discover_available_tools_activity,
    execute_agent_task_activity,
    persist_agent_memory_activity,
    publish_task_event_activity,
)
from ..interfaces import get_activity_services
from ..models import (
    AgentExecutionRequest,
    AgentExecutionResult,
)

logger = logging.getLogger(__name__)


@workflow.defn
class AgentExecutionWorkflow:
    """Simplified agent execution workflow that orchestrates activities.
    
    This workflow follows Temporal best practices:
    - Simple orchestration logic
    - All business logic delegated to activities
    - No complex reasoning loops in workflow
    - Proper error handling via Temporal retry mechanisms
    """

    def __init__(self):
        self.execution_metadata: Dict[str, Any] = {}

    @workflow.run
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Execute an agent task by orchestrating activities."""
        
        try:
            workflow.logger.info(f"Starting agent execution for task {request.task_id}")
            
            # Get injected services
            activity_services = get_activity_services()
            
            # Activity 1: Validate agent configuration
            validation_result = await workflow.execute_activity(
                validate_agent_configuration_activity,
                args=[request.agent_id, activity_services],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            
            if not validation_result.get("valid", False):
                return await self._handle_validation_failure(
                    request, validation_result, activity_services
                )
            
            # Activity 2: Discover available tools
            available_tools = await workflow.execute_activity(
                discover_available_tools_activity,
                args=[request.agent_id, activity_services],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            
            workflow.logger.info(f"Discovered {len(available_tools)} tools")
            
            # Activity 3: Execute agent task (core business logic)
            # This activity will contain all the reasoning logic that was previously in the workflow
            task_result = await workflow.execute_activity(
                execute_agent_task_activity,
                args=[request, available_tools, activity_services],
                start_to_close_timeout=timedelta(seconds=request.timeout_seconds),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=60),
                ),
            )
            
            # Activity 4: Persist agent memory
            memory_result = await workflow.execute_activity(
                persist_agent_memory_activity,
                args=[
                    request.agent_id,
                    request.task_id,
                    task_result.get("conversation_history", []),
                    task_result,
                    activity_services,
                ],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            
            # Activity 5: Publish completion event
            await workflow.execute_activity(
                publish_task_event_activity,
                args=[
                    "TaskCompleted",
                    {
                        "task_id": str(request.task_id),
                        "agent_id": str(request.agent_id),
                        "user_id": request.user_id,
                        "success": task_result.get("success", False),
                        "execution_metrics": task_result.get("execution_metrics", {}),
                        "timestamp": workflow.now().isoformat(),
                    },
                    activity_services,
                ],
                start_to_close_timeout=timedelta(seconds=30),
            )
            
            # Return result
            return AgentExecutionResult(
                task_id=request.task_id,
                agent_id=request.agent_id,
                success=task_result.get("success", False),
                final_response=task_result.get("final_response"),
                conversation_history=task_result.get("conversation_history", []),
                reasoning_iterations_used=task_result.get("reasoning_iterations", 0),
                total_tool_calls=task_result.get("total_tool_calls", 0),
                execution_duration_seconds=task_result.get("execution_duration_seconds", 0),
                agent_memory_updates=memory_result,
                artifacts=task_result.get("artifacts", []),
                error_message=task_result.get("error_message"),
            )
            
        except Exception as e:
            workflow.logger.error(f"Agent execution failed: {e}")
            # Create a default activity services if not available
            try:
                activity_services = get_activity_services()
            except:
                activity_services = None
            return await self._handle_workflow_failure(e, request, activity_services)

    async def _handle_validation_failure(
        self,
        request: AgentExecutionRequest,
        validation_result: Dict[str, Any],
        activity_services: Any,
    ) -> AgentExecutionResult:
        """Handle agent validation failures."""
        errors = validation_result.get("errors", [])
        error_msg = f"Agent validation failed: {errors}"
        workflow.logger.error(error_msg)
        
        # Publish failure event
        await workflow.execute_activity(
            publish_task_event_activity,
            args=[
                "TaskValidationFailed",
                {
                    "task_id": str(request.task_id),
                    "agent_id": str(request.agent_id),
                    "user_id": request.user_id,
                    "errors": errors,
                    "timestamp": workflow.now().isoformat(),
                },
                activity_services,
            ],
            start_to_close_timeout=timedelta(seconds=30),
        )
        
        return AgentExecutionResult(
            task_id=request.task_id,
            agent_id=request.agent_id,
            success=False,
            error_message=error_msg,
        )

    async def _handle_workflow_failure(
        self, error: Exception, request: AgentExecutionRequest, activity_services: Any
    ) -> AgentExecutionResult:
        """Handle workflow-level failures."""
        try:
            # Publish failure event
            await workflow.execute_activity(
                publish_task_event_activity,
                args=[
                    "TaskFailed",
                    {
                        "task_id": str(request.task_id),
                        "agent_id": str(request.agent_id),
                        "user_id": request.user_id,
                        "error": str(error),
                        "timestamp": workflow.now().isoformat(),
                    },
                    activity_services,
                ],
                start_to_close_timeout=timedelta(seconds=30),
            )
        except Exception as publish_error:
            workflow.logger.error(f"Failed to publish failure event: {publish_error}")
        
        return AgentExecutionResult(
            task_id=request.task_id,
            agent_id=request.agent_id,
            success=False,
            error_message=str(error),
        )

    @workflow.signal
    async def cancel_execution(self) -> None:
        """Signal to cancel the execution."""
        workflow.logger.info("Execution cancellation requested")
        # Temporal will handle cancellation automatically

    @workflow.query
    def get_execution_status(self) -> Dict[str, Any]:
        """Query current execution status."""
        return {
            "status": "running",
            "metadata": self.execution_metadata,
        } 