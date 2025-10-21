"""Temporal implementation of the workflow executor interface.

This implements the abstract workflow executor using Temporal as the backend,
while maintaining the clean abstraction layer.
"""

import asyncio
import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import TemporalError

from agentarea_common.utils.types import Artifact, Message, TextPart
from agentarea_common.workflow.executor import (
    TaskExecutorInterface,
    WorkflowConfig,
    WorkflowExecutor,
    WorkflowResult,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)


def _extract_a2a_message_from_workflow_result(result: dict[str, Any]) -> dict[str, Any]:
    """Extract A2A-compatible message from workflow result.

    Converts workflow events into A2A Message format with proper parts structure.
    """
    if not result or not isinstance(result, dict):
        return {}

    # Navigate to the nested result structure: result.result.events
    nested_result = result.get("result", {})
    if not nested_result:
        return {}

    events = nested_result.get("events", [])
    if not events:
        return {}

    # Find the TaskProgress event with agent response
    agent_response_text = ""
    session_id = None
    usage_metadata = None

    for event in events:
        if event.get("event_type") == "TaskProgress":
            original_event = event.get("original_event", {})
            content = original_event.get("content", {})
            parts = content.get("parts", [])

            # Extract text from parts
            for part in parts:
                if part.get("text"):
                    agent_response_text = part["text"]
                    break

            # Extract session_id and metadata
            session_id = event.get("session_id")
            usage_metadata = original_event.get("usage_metadata")
            break

    if not agent_response_text:
        return {}

    # Create A2A-compatible response
    a2a_message = Message(role="agent", parts=[TextPart(text=agent_response_text)])

    # Create A2A-compatible artifact
    a2a_artifact = Artifact(
        name="agent_response",
        description="Agent response to user query",
        parts=[TextPart(text=agent_response_text)],
        metadata={
            "session_id": session_id,
            "usage_metadata": usage_metadata,
            "source": "workflow_execution",
        },
    )

    return {
        "message": a2a_message.model_dump(),
        "artifacts": [a2a_artifact.model_dump()],
        "session_id": session_id,
        "usage_metadata": usage_metadata,
    }


class TemporalWorkflowExecutor(WorkflowExecutor):
    """Temporal implementation of WorkflowExecutor."""

    def __init__(
        self,
        client: Client | None = None,
        namespace: str = "default",
        server_url: str = "localhost:7233",
    ):
        self.client = client
        self.namespace = namespace
        self.server_url = server_url
        self._connected = False

    async def _ensure_connected(self):
        """Ensure client is connected to Temporal server."""
        if not self._connected and self.client is None:
            try:
                # Connect to configured Temporal server
                logger.info(
                    f"Connecting to Temporal server at {self.server_url} "
                    f"with namespace {self.namespace}"
                )
                self.client = await Client.connect(
                    self.server_url,
                    namespace=self.namespace,
                    data_converter=pydantic_data_converter,
                )
                self._connected = True
                logger.info("Successfully connected to Temporal server")
            except Exception as e:
                logger.error(f"Failed to connect to Temporal server at {self.server_url}: {e}")
                raise ConnectionError(f"Cannot connect to Temporal server: {e}") from e

    def _convert_config_to_temporal(self, config: WorkflowConfig | None) -> dict[str, Any]:
        """Convert our WorkflowConfig to Temporal parameters."""
        if not config:
            return {}

        temporal_params = {}

        if config.timeout:
            temporal_params["execution_timeout"] = config.timeout

        if config.task_queue:
            temporal_params["task_queue"] = config.task_queue

        # Convert retry policy
        temporal_params["retry_policy"] = RetryPolicy(
            maximum_attempts=config.retry_attempts,
            initial_interval=config.retry_initial_interval,
            maximum_interval=config.retry_max_interval,
        )

        return temporal_params

    def _temporal_status_to_workflow_status(self, temporal_status: str) -> WorkflowStatus:
        """Convert Temporal workflow status to our WorkflowStatus enum."""
        status_mapping = {
            "RUNNING": WorkflowStatus.RUNNING,
            "COMPLETED": WorkflowStatus.COMPLETED,
            "FAILED": WorkflowStatus.FAILED,
            "CANCELED": WorkflowStatus.CANCELLED,
            "TERMINATED": WorkflowStatus.TERMINATED,
        }
        return status_mapping.get(temporal_status, WorkflowStatus.UNKNOWN)

    async def start_workflow(
        self,
        workflow_name: str,
        workflow_id: str,
        args: dict[str, Any],
        config: WorkflowConfig | None = None,
    ) -> str:
        """Start a Temporal workflow."""
        await self._ensure_connected()

        temporal_params = self._convert_config_to_temporal(config)

        # Import workflow class dynamically based on name
        if workflow_name == "AgentTaskWorkflow":
            from agentarea_tasks.workflows.agent_task_workflow import AgentTaskWorkflow

            workflow_class = AgentTaskWorkflow.run
        elif workflow_name == "AgentExecutionWorkflow":
            from agentarea_execution.workflows.agent_execution_workflow import (
                AgentExecutionWorkflow,
            )

            workflow_class = AgentExecutionWorkflow.run
        else:
            raise ValueError(f"Unknown workflow: {workflow_name}")

        try:
            # Convert args dict to positional arguments based on workflow type
            if workflow_name == "AgentTaskWorkflow":
                # Based on AgentTaskWorkflow.run signature: agent_id, task_id, query, user_id, task_parameters, metadata
                workflow_args = [
                    args.get("agent_id"),
                    args.get("task_id"),
                    args.get("query"),
                    args.get("user_id"),
                    args.get("task_parameters", {}),
                    args.get("metadata", {}),
                ]
            elif workflow_name == "AgentExecutionWorkflow":
                # Based on AgentExecutionWorkflow.run signature: takes AgentExecutionRequest
                from uuid import UUID

                from agentarea_execution.models import AgentExecutionRequest

                logger.info(f"workspace_id: {args['workspace_id']}")

                # Convert string UUIDs back to UUID objects
                execution_request = AgentExecutionRequest(
                    task_id=UUID(args["task_id"]),
                    agent_id=UUID(args["agent_id"]),
                    user_id=args["user_id"],
                    workspace_id=args["workspace_id"],
                    task_query=args["task_query"],
                    task_parameters=args.get("task_parameters", {}),
                    timeout_seconds=args.get("timeout_seconds", 300),
                    max_reasoning_iterations=args.get("max_reasoning_iterations", 10),
                    enable_agent_communication=args.get("enable_agent_communication", False),
                    requires_human_approval=args.get("requires_human_approval", False),
                    workflow_metadata=args.get("workflow_metadata", {}),
                )
                workflow_args = [execution_request]
            else:
                workflow_args = [args]

            # Add workflow ID reuse policy to handle duplicates gracefully
            temporal_params["id_reuse_policy"] = WorkflowIDReusePolicy.ALLOW_DUPLICATE

            handle = await self.client.start_workflow(
                workflow_class,
                args=workflow_args,  # Pass as args parameter
                id=workflow_id,
                **temporal_params,
            )

            logger.info(f"Started Temporal workflow {workflow_id} ({workflow_name})")
            return handle.id

        except Exception as e:
            # Handle workflow already started error gracefully
            if "already started" in str(e).lower() or "WorkflowAlreadyStartedError" in str(e):
                logger.info(
                    f"Workflow {workflow_id} already running - returning existing workflow ID"
                )
                return workflow_id
            else:
                logger.error(f"Failed to start workflow {workflow_id}: {e}")
                raise

    async def get_workflow_status(self, workflow_id: str) -> WorkflowResult:
        """Get Temporal workflow status."""
        await self._ensure_connected()

        try:
            handle = self.client.get_workflow_handle(workflow_id)
            description = await handle.describe()

            # Handle execution_time safely - it might be timedelta or datetime
            execution_time_seconds = None
            if description.execution_time:
                if hasattr(description.execution_time, "total_seconds"):
                    execution_time_seconds = description.execution_time.total_seconds()
                else:
                    # If it's not a timedelta, try to convert or log warning
                    logger.warning(
                        f"Unexpected execution_time type: {type(description.execution_time)}"
                    )
                    execution_time_seconds = None

            # Get result if workflow is completed
            result = None
            if description.status.name.lower() in ["completed"]:
                try:
                    result = await handle.result()
                    if not isinstance(result, dict):
                        result = {"result": result}
                except Exception as e:
                    logger.warning(f"Failed to get workflow result for {workflow_id}: {e}")
                    result = None

            return WorkflowResult(
                workflow_id=workflow_id,
                status=self._temporal_status_to_workflow_status(description.status.name),
                start_time=description.start_time.isoformat() if description.start_time else None,
                end_time=description.close_time.isoformat() if description.close_time else None,
                execution_time=execution_time_seconds,
                result=result,
            )

        except TemporalError as e:
            if "not found" in str(e).lower():
                return WorkflowResult(
                    workflow_id=workflow_id,
                    status=WorkflowStatus.UNKNOWN,
                    error="Workflow not found",
                )
            else:
                raise
        except Exception as e:
            logger.error(f"Failed to get workflow status for {workflow_id}: {e}")
            return WorkflowResult(
                workflow_id=workflow_id, status=WorkflowStatus.UNKNOWN, error=str(e)
            )

    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a Temporal workflow."""
        await self._ensure_connected()

        try:
            handle = self.client.get_workflow_handle(workflow_id)
            await handle.cancel()
            logger.info(f"Cancelled workflow {workflow_id}")
            return True

        except TemporalError as e:
            if "not found" in str(e).lower():
                logger.warning(f"Cannot cancel workflow {workflow_id}: not found")
                return False
            else:
                raise
        except Exception as e:
            logger.error(f"Failed to cancel workflow {workflow_id}: {e}")
            return False

    async def wait_for_result(
        self, workflow_id: str, timeout: timedelta | None = None
    ) -> WorkflowResult:
        """Wait for Temporal workflow completion."""
        await self._ensure_connected()

        try:
            handle = self.client.get_workflow_handle(workflow_id)

            # Wait for result with timeout
            if timeout:
                result = await asyncio.wait_for(handle.result(), timeout.total_seconds())
            else:
                result = await handle.result()

            # Get final status
            description = await handle.describe()

            # Handle execution_time safely - it might be timedelta or datetime
            execution_time_seconds = None
            if description.execution_time:
                if hasattr(description.execution_time, "total_seconds"):
                    execution_time_seconds = description.execution_time.total_seconds()
                else:
                    logger.warning(
                        f"Unexpected execution_time type in wait_for_result: {type(description.execution_time)}"
                    )

            return WorkflowResult(
                workflow_id=workflow_id,
                status=self._temporal_status_to_workflow_status(description.status.name),
                result=result if isinstance(result, dict) else {"result": result},
                start_time=description.start_time.isoformat() if description.start_time else None,
                end_time=description.close_time.isoformat() if description.close_time else None,
                execution_time=execution_time_seconds,
            )

        except TimeoutError as e:
            raise TimeoutError(f"Workflow {workflow_id} did not complete within timeout") from e
        except Exception as e:
            logger.error(f"Failed to wait for workflow {workflow_id}: {e}")
            return WorkflowResult(
                workflow_id=workflow_id, status=WorkflowStatus.FAILED, error=str(e)
            )

    async def signal_workflow(self, workflow_id: str, signal_name: str, data: Any = None) -> None:
        """Send signal to Temporal workflow."""
        await self._ensure_connected()

        try:
            handle = self.client.get_workflow_handle(workflow_id)
            await handle.signal(signal_name, data)
            logger.debug(f"Sent signal {signal_name} to workflow {workflow_id}")

        except Exception as e:
            logger.error(f"Failed to signal workflow {workflow_id}: {e}")
            raise

    async def query_workflow(
        self, workflow_id: str, query_name: str, args: dict[str, Any] | None = None
    ) -> Any:
        """Query Temporal workflow."""
        await self._ensure_connected()

        try:
            handle = self.client.get_workflow_handle(workflow_id)
            result = await handle.query(query_name, *(args.values() if args else []))
            return result

        except Exception as e:
            logger.error(f"Failed to query workflow {workflow_id}: {e}")
            raise


class TemporalTaskExecutor(TaskExecutorInterface):
    """High-level task executor using Temporal workflows.

    This is the main class that AgentArea services will use.
    """

    def __init__(
        self,
        workflow_executor: TemporalWorkflowExecutor | None = None,
        default_task_queue: str = "agent-tasks",
    ):
        self.workflow_executor = workflow_executor or TemporalWorkflowExecutor()
        self.default_task_queue = default_task_queue

    async def execute_task_async(
        self,
        task_id: str,
        agent_id: UUID,
        description: str,
        user_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Execute agent task using Temporal workflow."""
        workflow_id = f"agent-task-{task_id}"

        # Prepare workflow arguments
        workflow_args = {
            "agent_id": str(agent_id),
            "task_id": task_id,
            "query": description,
            "user_id": user_id or "system",
            "task_parameters": task_parameters or {},
            "metadata": metadata or {},
        }

        # Configure workflow
        config = WorkflowConfig(
            timeout=timedelta(days=7),  # Tasks can run for a week
            task_queue=self.default_task_queue,
            retry_attempts=3,
        )

        # Start workflow - this returns immediately!
        execution_id = await self.workflow_executor.start_workflow(
            workflow_name="AgentTaskWorkflow",
            workflow_id=workflow_id,
            args=workflow_args,
            config=config,
        )

        logger.info(f"Started agent task {task_id} with execution ID {execution_id}")
        return execution_id

    async def get_task_status(self, execution_id: str) -> dict[str, Any]:
        """Get task status from workflow."""
        result = await self.workflow_executor.get_workflow_status(execution_id)

        # Extract A2A-compatible message and artifacts from workflow result
        a2a_data = _extract_a2a_message_from_workflow_result(result.result) if result.result else {}

        return {
            "execution_id": execution_id,
            "status": result.status.value,
            "start_time": result.start_time,
            "end_time": result.end_time,
            "execution_time": result.execution_time,
            "error": result.error,
            "result": result.result,
            # A2A-compatible fields for frontend
            "message": a2a_data.get("message"),
            "artifacts": a2a_data.get("artifacts"),
            "session_id": a2a_data.get("session_id"),
            "usage_metadata": a2a_data.get("usage_metadata"),
        }

    async def cancel_task(self, execution_id: str) -> bool:
        """Cancel running task."""
        return await self.workflow_executor.cancel_workflow(execution_id)

    async def wait_for_task_completion(
        self, execution_id: str, timeout: timedelta | None = None
    ) -> dict[str, Any]:
        """Wait for task completion."""
        result = await self.workflow_executor.wait_for_result(execution_id, timeout)

        return {
            "execution_id": execution_id,
            "status": result.status.value,
            "result": result.result,
            "error": result.error,
            "execution_time": result.execution_time,
        }
