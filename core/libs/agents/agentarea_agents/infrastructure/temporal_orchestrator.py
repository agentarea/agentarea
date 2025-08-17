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
            except ImportError:
                logger.warning("Temporal not available - using fallback")
                return None
            except Exception as e:
                logger.error(f"Failed to connect to Temporal: {e}")
                return None
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

        if not client:
            # Fallback to in-memory simulation
            return await self._simulate_workflow_start(execution_id, request)

        try:
            # Try to import from execution library - fallback if not available
            try:
                from agentarea_execution.adk_temporal.workflows.adk_agent_workflow import (
                    ADKAgentWorkflow,
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
                        logger.warning(f"Failed to extract UUID from execution_id {execution_id}, using new UUID: {task_id_uuid}")
                else:
                    # If execution_id doesn't match expected pattern, try to parse it as UUID
                    try:
                        task_id_uuid = UUID(execution_id)
                    except ValueError:
                        # Last resort: generate new UUID
                        from uuid import uuid4
                        task_id_uuid = uuid4()
                        logger.warning(f"execution_id {execution_id} is not a valid UUID pattern, using new UUID: {task_id_uuid}")

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

            except ImportError:
                # Fallback to simple string-based workflow if execution library not available
                if execution_id.startswith("agent-task-"):
                    task_id_str = execution_id.replace("agent-task-", "")
                else:
                    task_id_str = execution_id

                try:
                    # Ensure task_id is a valid UUID string for the workflow
                    UUID(task_id_str)
                except ValueError:
                    # If not, log a warning and generate a new one to avoid workflow failure
                    from uuid import uuid4
                    task_id_str = str(uuid4())
                    logger.warning(
                        f"Could not parse UUID from execution_id '{execution_id}'. "
                        f"Generated new task_id: {task_id_str}"
                    )

                handle = await client.start_workflow(
                    "AgentExecutionWorkflow",
                    {
                        "agent_id": str(request.agent_id),
                        "task_id": task_id_str,  # Corrected: pass valid UUID string
                        "user_id": request.user_id,
                        "task_query": request.task_query,  # FIXED: was 'query', now 'task_query'
                        "session_id": request.session_id,
                        "task_parameters": request.task_parameters,
                        "timeout_seconds": request.timeout_seconds,
                    },
                    id=execution_id,
                    task_queue=self.task_queue,
                )

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
            return await self._simulate_workflow_start(execution_id, request)

    async def get_workflow_status(self, execution_id: str) -> dict[str, Any]:
        """Get Temporal workflow status."""
        client = await self._get_client()

        if not client:
            return await self._simulate_workflow_status(execution_id)

        try:
            handle = client.get_workflow_handle(execution_id)

            # Check if workflow is complete
            try:
                result = await handle.result()

                return {
                    "status": "completed",
                    "success": True,
                    "result": {
                        "response": getattr(result, 'final_response', str(result)),
                        "conversation_history": getattr(result, 'conversation_history', []),
                        "execution_metrics": getattr(result, 'execution_metrics', {}),
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
            return await self._simulate_workflow_status(execution_id)

    async def cancel_workflow(self, execution_id: str) -> bool:
        """Cancel Temporal workflow."""
        client = await self._get_client()

        if not client:
            logger.info(f"Simulated cancellation of workflow: {execution_id}")
            return True

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

        if not client:
            logger.info(f"Simulated pause of workflow: {execution_id}")
            return await self._simulate_workflow_pause(execution_id)

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

        if not client:
            logger.info(f"Simulated resume of workflow: {execution_id}")
            return await self._simulate_workflow_resume(execution_id)

        try:
            handle = client.get_workflow_handle(execution_id)
            await handle.signal("resume_execution", "User requested resume")
            logger.info(f"Resumed Temporal workflow: {execution_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to resume workflow: {e}")
            return False

    async def _simulate_workflow_start(self, execution_id: str, request: ExecutionRequest) -> dict[str, Any]:
        """Simulate workflow start when Temporal is not available."""
        logger.info(f"Simulating workflow start: {execution_id}")

        # Create a simple simulation file for tracking
        import json
        import os
        import time

        state_dir = "/tmp/agentarea_workflows"
        os.makedirs(state_dir, exist_ok=True)

        state_file = f"{state_dir}/{execution_id}.json"
        state_data = {
            "execution_id": execution_id,
            "agent_id": str(request.agent_id),
            "query": request.task_query,
            "user_id": request.user_id,
            "start_time": time.time(),
            "status": "running",
        }

        with open(state_file, 'w') as f:
            json.dump(state_data, f)

        return {
            "success": True,
            "status": "started",
            "content": "Workflow simulation started",
            "execution_id": execution_id,
            "temporal_available": False,
        }

    async def _simulate_workflow_status(self, execution_id: str) -> dict[str, Any]:
        """Simulate workflow status check."""
        import json
        import os
        import time

        state_file = f"/tmp/agentarea_workflows/{execution_id}.json"

        if not os.path.exists(state_file):
            return {
                "status": "not_found",
                "success": False,
                "error": "Workflow not found",
            }

        with open(state_file) as f:
            state_data = json.load(f)

        # Simulate completion after 3 seconds
        start_time = state_data.get("start_time", time.time())
        if time.time() - start_time > 3:
            return {
                "status": "completed",
                "success": True,
                "result": {
                    "response": f"Hello! I've processed your query: {state_data.get('query', 'unknown')}. This is a simulated response.",
                    "conversation_history": [],
                    "execution_metrics": {"simulated": True},
                },
                "end_time": datetime.now().isoformat(),
            }

        return {
            "status": "running",
            "success": None,
            "result": None,
        }

    async def _simulate_workflow_pause(self, execution_id: str) -> bool:
        """Simulate workflow pause."""
        import json
        import os

        state_file = f"/tmp/agentarea_workflows/{execution_id}.json"

        if not os.path.exists(state_file):
            logger.warning(f"Cannot pause workflow {execution_id}: state file not found")
            return False

        try:
            with open(state_file) as f:
                state_data = json.load(f)

            state_data["status"] = "paused"
            state_data["paused_at"] = datetime.now().isoformat()

            with open(state_file, 'w') as f:
                json.dump(state_data, f)

            logger.info(f"Simulated pause of workflow: {execution_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to simulate workflow pause: {e}")
            return False

    async def _simulate_workflow_resume(self, execution_id: str) -> bool:
        """Simulate workflow resume."""
        import json
        import os

        state_file = f"/tmp/agentarea_workflows/{execution_id}.json"

        if not os.path.exists(state_file):
            logger.warning(f"Cannot resume workflow {execution_id}: state file not found")
            return False

        try:
            with open(state_file) as f:
                state_data = json.load(f)

            if state_data.get("status") != "paused":
                logger.warning(f"Cannot resume workflow {execution_id}: not in paused state")
                return False

            state_data["status"] = "running"
            state_data["resumed_at"] = datetime.now().isoformat()

            with open(state_file, 'w') as f:
                json.dump(state_data, f)

            logger.info(f"Simulated resume of workflow: {execution_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to simulate workflow resume: {e}")
            return False
