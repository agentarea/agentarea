"""Temporal workflow for stopping an MCP server instance."""

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from typing import Any

from .constants import (
    CONTAINER_STOP_TIMEOUT,
    DB_UPDATE_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    EVENT_PUBLISH_RETRY_ATTEMPTS,
    EVENT_PUBLISH_TIMEOUT,
)
from .models import (
    DeleteContainerRequest,
    DeleteContainerResult,
    PublishMCPEventRequest,
    PublishMCPEventResult,
    StopMCPInstanceRequest,
    StopMCPInstanceResult,
    UpdateInstanceStatusRequest,
    UpdateInstanceStatusResult,
)


@workflow.defn
class StopMCPInstanceWorkflow:
    """Orchestrates stopping an MCP server instance.

    Steps:
    1. Update DB status to "stopping"
    2. Call Go MCP Manager DELETE /instances/:id
    3. Update DB status to "stopped"

    Workflow ID pattern: mcp-stop-{instance_id}
    """

    def __init__(self) -> None:
        self._status = "stopping"
        self._error: str | None = None

    @workflow.run
    async def run(self, request: StopMCPInstanceRequest) -> StopMCPInstanceResult:
        instance_id = request.instance_id
        try:
            # Step 1: Update status to "stopping"
            self._status = "stopping"
            await self._update_status(request, "stopping")
            await self._publish_event(request, "mcp.server.stopping")

            # Step 2: Delete container via Go manager (skip for url-type)
            spec_type = request.json_spec.get("type", "docker")
            if spec_type != "url":
                delete_result = await workflow.execute_activity(
                    "delete_mcp_container_activity",
                    args=[DeleteContainerRequest(instance_id=instance_id)],
                    start_to_close_timeout=CONTAINER_STOP_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
                    result_type=DeleteContainerResult,
                )

                if not delete_result.success:
                    raise RuntimeError(
                        f"Container deletion failed: {delete_result.error}"
                    )

            # Step 3: Mark stopped
            self._status = "stopped"
            await self._update_status(request, "stopped")
            await self._publish_event(request, "mcp.server.stopped")

            return StopMCPInstanceResult(
                instance_id=instance_id,
                success=True,
                status="stopped",
            )

        except Exception as e:
            workflow.logger.error("StopMCPInstanceWorkflow failed: %s", e)
            self._status = "failed"
            self._error = str(e)

            try:
                await self._update_status(request, "failed")
            except Exception as status_err:
                workflow.logger.warning("Failed to set status to failed: %s", status_err)
            try:
                await self._publish_event(
                    request,
                    "mcp.server.failed",
                    {"error": str(e)},
                )
            except Exception as event_err:
                workflow.logger.warning("Failed to publish failure event: %s", event_err)

            return StopMCPInstanceResult(
                instance_id=instance_id,
                success=False,
                status="failed",
                error_message=str(e),
            )

    async def _update_status(
        self, request: StopMCPInstanceRequest, status: str
    ) -> None:
        await workflow.execute_activity(
            "update_mcp_instance_status_activity",
            args=[
                UpdateInstanceStatusRequest(
                    instance_id=request.instance_id,
                    status=status,
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                )
            ],
            start_to_close_timeout=DB_UPDATE_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            result_type=UpdateInstanceStatusResult,
        )

    async def _publish_event(
        self,
        request: StopMCPInstanceRequest,
        event_type: str,
        extra_data: dict[str, Any] | None = None,
    ) -> None:
        event_data: dict[str, Any] = {
            "instance_id": str(request.instance_id),
            "status": self._status,
        }
        if extra_data:
            event_data.update(extra_data)

        await workflow.execute_activity(
            "publish_mcp_event_activity",
            args=[
                PublishMCPEventRequest(
                    instance_id=request.instance_id,
                    workspace_id=request.workspace_id,
                    user_id=request.user_id,
                    event_type=event_type,
                    event_data=event_data,
                )
            ],
            start_to_close_timeout=EVENT_PUBLISH_TIMEOUT,
            retry_policy=RetryPolicy(
                maximum_attempts=EVENT_PUBLISH_RETRY_ATTEMPTS
            ),
            result_type=PublishMCPEventResult,
        )

    @workflow.query
    def get_current_state(self) -> dict[str, Any]:
        return {"status": self._status, "error": self._error}
