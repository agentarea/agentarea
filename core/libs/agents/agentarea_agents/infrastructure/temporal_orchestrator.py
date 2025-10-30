"""Temporal workflow orchestrator implementation."""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from ..application.execution_service import WorkflowOrchestratorInterface
from ..domain.interfaces import ExecutionRequest

logger = logging.getLogger(__name__)


class TemporalWorkflowOrchestrator(WorkflowOrchestratorInterface):
    """Temporal-specific implementation of workflow orchestration."""

    def __init__(
        self,
        temporal_address: str,
        task_queue: str,
        max_concurrent_activities: int,
        max_concurrent_workflows: int,
    ):
        """Initialize with required configuration - no defaults allowed."""
        if not temporal_address:
            raise ValueError("temporal_address must be provided")
        if not task_queue:
            raise ValueError("task_queue must be provided")

        self.temporal_address = temporal_address
        self.task_queue = task_queue
        self.max_concurrent_activities = max_concurrent_activities
        self.max_concurrent_workflows = max_concurrent_workflows
        self._client = None

    async def _get_client(self):
        """Get Temporal client, create if needed."""
        if self._client is None:
            try:
                from temporalio.client import Client
                from temporalio.contrib.pydantic import pydantic_data_converter

                self._client = await Client.connect(
                    self.temporal_address,
                    data_converter=pydantic_data_converter,
                )
                logger.info(f"Connected to Temporal at {self.temporal_address}")
            except ImportError as e:
                logger.error(f"Temporal library not installed: {e}")
                raise RuntimeError(
                    "Temporal integration is not ready (missing 'temporalio')"
                ) from e
            except Exception as e:
                logger.error(f"Failed to connect to Temporal: {e}")
                raise RuntimeError(f"Temporal client connection failed: {e}") from e
        return self._client

    async def close(self):
        """Close Temporal client connection."""
        if self._client:
            try:
                await self._client.close()
                logger.info("Closed Temporal client connection")
            except Exception as e:
                logger.warning(f"Error closing Temporal client: {e}")
            finally:
                self._client = None

    async def start_workflow(self, execution_id: str, request: ExecutionRequest) -> dict[str, Any]:
        """Start Temporal workflow execution."""
        client = await self._get_client()

        try:
            # Try to import from execution library - fallback if not available
            try:
                from agentarea_execution.adk_temporal.workflows.adk_agent_workflow import (
                    ADKAgentWorkflow as AgentExecutionWorkflow,
                )
                from agentarea_execution.models import AgentExecutionRequest

                # Extract task_id UUID from execution_id pattern
                # execution_id format: "agent-task-{uuid}"
                if execution_id.startswith("agent-task-"):
                    task_id_str = execution_id.replace("agent-task-", "")
                    try:
                        task_id_uuid = UUID(task_id_str)
                    except ValueError:
                        # If extraction fails, generate a new UUID
                        from uuid import uuid4

                        task_id_uuid = uuid4()
                        logger.warning(
                            f"Failed to extract UUID from execution_id {execution_id}, using new UUID: {task_id_uuid}"
                        )
                else:
                    # If execution_id doesn't match expected pattern, try to parse it as UUID
                    try:
                        task_id_uuid = UUID(execution_id)
                    except ValueError:
                        # Last resort: generate new UUID
                        from uuid import uuid4

                        task_id_uuid = uuid4()
                        logger.warning(
                            f"execution_id {execution_id} is not a valid UUID pattern, using new UUID: {task_id_uuid}"
                        )

                # Convert to execution request format with proper UUID
                exec_request = AgentExecutionRequest(
                    task_id=task_id_uuid,  # Now using proper UUID instead of string
                    agent_id=request.agent_id,
                    user_id=request.user_id,
                    task_query=request.task_query,
                    task_parameters=request.task_parameters,
                    timeout_seconds=request.timeout_seconds,
                )

                # Start the workflow
                handle = await client.start_workflow(
                    AgentExecutionWorkflow.run,
                    exec_request,
                    id=execution_id,
                    task_queue=self.task_queue,
                )

            except ImportError as e:
                logger.error(f"Agent execution library not available: {e}")
                raise RuntimeError(
                    "Agent execution integration is not ready (missing 'agentarea_execution')"
                ) from e

            logger.info(f"Started Temporal workflow: {execution_id}")

            return {
                "success": True,
                "status": "started",
                "content": "Workflow started successfully",
                "execution_id": execution_id,
                "workflow_id": handle.id,
            }

        except Exception as e:
            logger.error(f"Failed to start Temporal workflow: {e}")
            raise RuntimeError(f"Failed to start Temporal workflow: {e}") from e

    async def get_workflow_status(self, execution_id: str) -> dict[str, Any]:
        """Get Temporal workflow status."""
        client = await self._get_client()

        try:
            handle = client.get_workflow_handle(execution_id)

            # Check if workflow is complete
            try:
                result = await handle.result()

                return {
                    "status": "completed",
                    "success": True,
                    "result": {
                        "response": getattr(result, "final_response", str(result)),
                        "conversation_history": getattr(result, "conversation_history", []),
                        "execution_metrics": getattr(result, "execution_metrics", {}),
                    },
                    "start_time": None,  # TODO: Get from Temporal
                    "end_time": datetime.now().isoformat(),
                }

            except Exception:
                # Workflow still running or failed
                return {
                    "status": "running",
                    "success": None,
                    "result": None,
                }

        except Exception as e:
            logger.error(f"Failed to get workflow status: {e}")
            raise RuntimeError(f"Failed to get workflow status: {e}") from e

    async def cancel_workflow(self, execution_id: str) -> bool:
        """Cancel Temporal workflow."""
        client = await self._get_client()

        try:
            handle = client.get_workflow_handle(execution_id)
            await handle.cancel()
            logger.info(f"Cancelled Temporal workflow: {execution_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel workflow: {e}")
            return False

    async def pause_workflow(self, execution_id: str) -> bool:
        """Pause Temporal workflow using signals."""
        client = await self._get_client()

        try:
            handle = client.get_workflow_handle(execution_id)
            await handle.signal("pause_execution", "User requested pause")
            logger.info(f"Paused Temporal workflow: {execution_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to pause workflow: {e}")
            return False

    async def resume_workflow(self, execution_id: str) -> bool:
        """Resume Temporal workflow using signals."""
        client = await self._get_client()

        try:
            handle = client.get_workflow_handle(execution_id)
            await handle.signal("resume_execution", "User requested resume")
            logger.info(f"Resumed Temporal workflow: {execution_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to resume workflow: {e}")
            return False
