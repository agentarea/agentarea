"""Temporal workflow for starting an MCP server instance."""

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    import asyncio
    from typing import Any

from .constants import (
    CONTAINER_CREATE_RETRY_ATTEMPTS,
    CONTAINER_START_TIMEOUT,
    DB_UPDATE_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    EVENT_PUBLISH_RETRY_ATTEMPTS,
    EVENT_PUBLISH_TIMEOUT,
    HEALTH_POLL_INTERVAL_SECONDS,
    HEALTH_POLL_MAX_ATTEMPTS,
    HEALTH_POLL_TIMEOUT,
    TOOL_DISCOVERY_TIMEOUT,
)
from .models import (
    CreateContainerRequest,
    CreateContainerResult,
    DiscoverToolsRequest,
    DiscoverToolsResult,
    PollContainerHealthRequest,
    PollContainerHealthResult,
    PublishMCPEventRequest,
    PublishMCPEventResult,
    ResolveAuthHeadersRequest,
    ResolveAuthHeadersResult,
    StartMCPInstanceRequest,
    StartMCPInstanceResult,
    UpdateInstanceStatusRequest,
    UpdateInstanceStatusResult,
)


@workflow.defn
class StartMCPInstanceWorkflow:
    """Orchestrates starting an MCP server instance end-to-end.

    Steps:
    1. Update DB status to "starting"
    2. Resolve environment variables from secret manager
    3. Call Go MCP Manager to create/start container
    4. Poll health until container is healthy
    5. Update DB status to "running"
    6. Discover tools from the MCP server
    7. Store tools in DB json_spec

    Workflow ID pattern: mcp-start-{instance_id}
    """

    def __init__(self) -> None:
        self._status = "pending"
        self._error: str | None = None
        self._tools_discovered = 0

    @workflow.run
    async def run(self, request: StartMCPInstanceRequest) -> StartMCPInstanceResult:
        instance_id = request.instance_id
        try:
            # Step 1: Update status to "starting"
            self._status = "starting"
            await self._update_status(request, "starting")
            await self._publish_event(request, "mcp.server.starting")

            # Step 2: Secrets are resolved by Go MCP Manager directly from
            # encrypted_secrets table. No need to pass secrets through Temporal
            # history — this avoids storing plaintext secrets in workflow state.

            json_spec_with_env = dict(request.json_spec)

            # Determine spec type — url-type MCPs skip container lifecycle
            spec_type = json_spec_with_env.get("type", "docker")
            is_url_type = spec_type == "url"

            if not is_url_type:
                # Step 3: Create container via Go manager
                self._status = "creating_container"
                create_result = await workflow.execute_activity(
                    "create_mcp_container_activity",
                    args=[
                        CreateContainerRequest(
                            instance_id=instance_id,
                            instance_name=request.instance_name,
                            workspace_id=request.workspace_id,
                            json_spec=json_spec_with_env,
                        )
                    ],
                    start_to_close_timeout=CONTAINER_START_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=CONTAINER_CREATE_RETRY_ATTEMPTS),
                    result_type=CreateContainerResult,
                )

                if not create_result.success:
                    raise RuntimeError(f"Container creation failed: {create_result.error}")

                # Step 4: Poll health until healthy
                self._status = "polling_health"
                await self._publish_event(request, "mcp.server.health.check")
                healthy = await self._poll_until_healthy(instance_id)

                if not healthy:
                    raise RuntimeError("Container failed to become healthy within timeout")

            # Step 5: Mark running
            self._status = "running"
            await self._update_status(request, "running")
            await self._publish_event(request, "mcp.server.ready")

            # Step 5b: Resolve auth headers if auth_config_id is set
            auth_headers: dict[str, str] = {}
            try:
                auth_result = await workflow.execute_activity(
                    "resolve_auth_headers_activity",
                    args=[
                        ResolveAuthHeadersRequest(
                            instance_id=instance_id,
                            user_id=request.user_id,
                            workspace_id=request.workspace_id,
                        )
                    ],
                    start_to_close_timeout=DB_UPDATE_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
                    result_type=ResolveAuthHeadersResult,
                )
                if auth_result.headers:
                    auth_headers = auth_result.headers
            except Exception as auth_err:
                workflow.logger.warning("Auth header resolution failed (non-fatal): %s", auth_err)

            # Step 6: Discover tools (non-fatal if this fails)
            self._status = "discovering_tools"

            # For url-type, pass endpoint_url and headers directly
            discover_kwargs: dict[str, Any] = {
                "instance_id": instance_id,
                "instance_name": request.instance_name,
            }
            if is_url_type:
                discover_kwargs["endpoint_url"] = json_spec_with_env.get("endpoint_url")
                # Merge json_spec headers with auth headers (auth takes precedence)
                spec_headers = dict(json_spec_with_env.get("headers", {}))
                spec_headers.update(auth_headers)
                discover_kwargs["headers"] = spec_headers
            elif auth_headers:
                discover_kwargs["headers"] = auth_headers

            discover_result = await workflow.execute_activity(
                "discover_mcp_tools_activity",
                args=[DiscoverToolsRequest(**discover_kwargs)],
                start_to_close_timeout=TOOL_DISCOVERY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
                result_type=DiscoverToolsResult,
            )

            # Step 7: Store tools if discovered
            if discover_result.success and discover_result.tools:
                self._tools_discovered = len(discover_result.tools)
                await self._update_status(
                    request,
                    "running",
                    json_spec_patch={"available_tools": discover_result.tools},
                )
                await self._publish_event(
                    request,
                    "mcp.server.tools.discovered",
                    {"tools_count": self._tools_discovered},
                )
            else:
                workflow.logger.warning(
                    "Tool discovery did not find tools: %s",
                    discover_result.error,
                )

            self._status = "running"
            return StartMCPInstanceResult(
                instance_id=instance_id,
                success=True,
                status="running",
                tools_discovered=self._tools_discovered,
            )

        except Exception as e:
            workflow.logger.error("StartMCPInstanceWorkflow failed: %s", e)
            self._status = "failed"
            self._error = str(e)

            # Best-effort: update DB to "failed"
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

            return StartMCPInstanceResult(
                instance_id=instance_id,
                success=False,
                status="failed",
                error_message=str(e),
            )

    async def _poll_until_healthy(self, instance_id: Any) -> bool:
        """Poll Go Manager health endpoint until healthy or max attempts."""
        for _attempt in range(HEALTH_POLL_MAX_ATTEMPTS):
            health_result = await workflow.execute_activity(
                "poll_mcp_container_health_activity",
                args=[PollContainerHealthRequest(instance_id=instance_id)],
                start_to_close_timeout=HEALTH_POLL_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
                result_type=PollContainerHealthResult,
            )

            if health_result.healthy:
                return True

            # Terminal states — stop polling
            if health_result.status in ("error", "failed", "stopped"):
                workflow.logger.error("Container entered terminal state: %s", health_result.status)
                return False

            await asyncio.sleep(HEALTH_POLL_INTERVAL_SECONDS)

        return False

    async def _update_status(
        self,
        request: StartMCPInstanceRequest,
        status: str,
        json_spec_patch: dict[str, Any] | None = None,
    ) -> None:
        await workflow.execute_activity(
            "update_mcp_instance_status_activity",
            args=[
                UpdateInstanceStatusRequest(
                    instance_id=request.instance_id,
                    status=status,
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                    json_spec_patch=json_spec_patch,
                )
            ],
            start_to_close_timeout=DB_UPDATE_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            result_type=UpdateInstanceStatusResult,
        )

    async def _publish_event(
        self,
        request: StartMCPInstanceRequest,
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
            retry_policy=RetryPolicy(maximum_attempts=EVENT_PUBLISH_RETRY_ATTEMPTS),
            result_type=PublishMCPEventResult,
        )

    @workflow.query
    def get_current_state(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "error": self._error,
            "tools_discovered": self._tools_discovered,
        }
