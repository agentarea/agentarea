"""Temporal workflow orchestrator implementation."""

import logging
from inspect import isawaitable
from typing import Any
from uuid import UUID

from ..application.execution_service import WorkflowOrchestratorInterface
from ..domain.interfaces import ExecutionRequest

logger = logging.getLogger(__name__)


def _duration_seconds(value: Any) -> float | None:
    total_seconds = getattr(value, "total_seconds", None)
    if callable(total_seconds):
        result = total_seconds()
        return float(result) if isinstance(result, int | float) else None
    return None


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
                from agentarea_common.config import ObservabilitySettings
                from agentarea_common.observability import get_temporal_plugins, setup_otel
                from temporalio.client import Client
                from temporalio.contrib.pydantic import pydantic_data_converter

                observability_settings = ObservabilitySettings()
                setup_otel("agentarea-agents", observability_settings)
                self._client = await Client.connect(
                    self.temporal_address,
                    data_converter=pydantic_data_converter,
                    plugins=get_temporal_plugins(observability_settings),
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
                close = getattr(self._client, "close", None)
                if callable(close):
                    close_result = close()
                    if isawaitable(close_result):
                        await close_result
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
                from agentarea_execution.models import AgentExecutionRequest
                from agentarea_execution.workflows.agent_execution_workflow import (
                    AgentExecutionWorkflow,
                )

                # Extract task_id UUID from execution_id pattern
                # execution_id format: "task-{uuid}"
                if execution_id.startswith("task-"):
                    task_id_str = execution_id.replace("task-", "", 1)
                    try:
                        task_id_uuid = UUID(task_id_str)
                    except ValueError:
                        # If extraction fails, generate a new UUID
                        from uuid import uuid4

                        task_id_uuid = uuid4()
                        logger.warning(
                            f"Failed to extract UUID from execution_id "
                            f"{execution_id}, using new UUID: {task_id_uuid}"
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
                            f"execution_id {execution_id} is not a valid UUID "
                            f"pattern, using new UUID: {task_id_uuid}"
                        )

                # Ensure workspace_id is provided
                if not request.workspace_id:
                    raise ValueError("workspace_id must be provided for agent execution")

                # Convert to execution request format with proper UUID
                exec_request = AgentExecutionRequest(
                    task_id=task_id_uuid,  # Now using proper UUID instead of string
                    agent_id=request.agent_id,
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
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
            description = await handle.describe()
            temporal_status = description.status.name.lower()

            status_map = {
                "running": "running",
                "completed": "completed",
                "failed": "failed",
                "canceled": "cancelled",
                "terminated": "failed",
                "timed_out": "failed",
                "continued_as_new": "running",
            }
            mapped_status = status_map.get(temporal_status, temporal_status)

            response: dict[str, Any] = {
                "status": mapped_status,
                "success": True if mapped_status == "completed" else None,
                "result": None,
                "start_time": description.start_time.isoformat()
                if description.start_time
                else None,
                "end_time": description.close_time.isoformat() if description.close_time else None,
                "execution_time": _duration_seconds(getattr(description, "execution_time", None)),
            }

            if mapped_status == "completed":
                result = await handle.result()
                response["result"] = {
                    "response": getattr(result, "final_response", str(result)),
                    "conversation_history": getattr(result, "conversation_history", []),
                    "execution_metrics": getattr(result, "execution_metrics", {}),
                }
                response["success"] = True
            elif mapped_status in {"failed", "cancelled"}:
                # Best-effort extraction of terminal failure details.
                try:
                    await handle.result()
                except Exception as e:
                    response["error"] = str(e)
                    response["success"] = False

                    error_text = str(e).lower()
                    if (
                        "insufficient balance" in error_text
                        or "no resource package" in error_text
                        or "quota exceeded" in error_text
                    ):
                        response["status"] = "blocked"
                        response["error_type"] = "provider_quota_exceeded"

            return response

        except Exception as e:
            # Workflow-not-found is normal: callers ask about task IDs that
            # never started a workflow (UI optimistic refresh, fake IDs,
            # already-evicted history). Surface as ``unknown`` so the API
            # layer can map it to 404 instead of 500.
            if "not found" in str(e).lower() or "no execution" in str(e).lower():
                return {"status": "unknown", "success": False, "error": "Workflow not found"}
            logger.error(f"Failed to get workflow status: {e}")
            raise RuntimeError(f"Failed to get workflow status: {e}") from e

    async def get_workflow_effective_policy(self, execution_id: str) -> dict | None:
        """Read the effective governance policy from a running/closed workflow.

        Best-effort: returns ``None`` when the workflow is not found, has no
        queryable state, or carries no effective policy. Mirrors the
        not-found handling of :meth:`get_workflow_status`.
        """
        client = await self._get_client()

        try:
            handle = client.get_workflow_handle(execution_id)
            state = await handle.query("get_current_state")
            if not isinstance(state, dict):
                return None
            return state.get("effective_policy")
        except Exception as e:
            if "not found" in str(e).lower() or "no execution" in str(e).lower():
                return None
            logger.error(f"Failed to get workflow effective policy: {e}")
            return None

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

    async def send_a2ui_action(self, execution_id: str, action_data: dict) -> bool:
        """Send an A2UI user action to a running workflow via signal."""
        client = await self._get_client()

        try:
            handle = client.get_workflow_handle(execution_id)
            await handle.signal("handle_a2ui_action", action_data)
            logger.info(f"Sent A2UI action to workflow: {execution_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send A2UI action: {e}")
            return False

    async def resolve_escalation_workflow(
        self,
        execution_id: str,
        escalation_id: str,
        approved: bool,
        comment: str = "",
        resolved_by: str = "",
    ) -> bool:
        """Resolve a tool escalation in a Temporal workflow using signals."""
        client = await self._get_client()

        try:
            handle = client.get_workflow_handle(execution_id)
            await handle.signal(
                "resolve_escalation", args=[escalation_id, approved, comment, resolved_by]
            )
            logger.info(f"Resolved escalation {escalation_id} in workflow: {execution_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to resolve escalation in workflow: {e}")
            return False

    async def send_workflow_command(
        self, execution_id: str, command: str, payload: dict[str, Any]
    ) -> bool:
        """Send a generic command signal to a running Temporal workflow."""
        client = await self._get_client()

        try:
            handle = client.get_workflow_handle(execution_id)
            await handle.signal("workflow_command", args=[command, payload])
            logger.info(f"Sent workflow command '{command}' to workflow: {execution_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send workflow command '{command}' to {execution_id}: {e}")
            return False
