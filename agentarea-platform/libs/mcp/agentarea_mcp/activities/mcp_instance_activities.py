"""MCP instance lifecycle activities for Temporal workflows.

Activities:
1. update_mcp_instance_status_activity  -- DB status update
2. create_mcp_container_activity        -- HTTP POST to Go Manager
3. delete_mcp_container_activity        -- HTTP DELETE to Go Manager
4. poll_mcp_container_health_activity   -- HTTP GET to Go Manager health
5. discover_mcp_tools_activity          -- MCP client list_tools via gateway
6. publish_mcp_event_activity           -- Redis event publish for SSE
7. get_mcp_instance_environment_activity -- Resolve env vars from secrets
"""

import logging
from datetime import timedelta
from typing import Any

import httpx
from agentarea_execution.interfaces import ActivityDependencies
from temporalio import activity

logger = logging.getLogger(__name__)


def make_mcp_activities(dependencies: ActivityDependencies) -> list:
    """Factory function to create MCP lifecycle activities.

    Args:
        dependencies: ActivityDependencies (settings, event_broker, secret_manager_factory)

    Returns:
        List of activity functions ready for worker registration
    """
    from agentarea_mcp.workflows.models import (
        CreateContainerRequest,
        CreateContainerResult,
        DeleteContainerRequest,
        DeleteContainerResult,
        DiscoverToolsRequest,
        DiscoverToolsResult,
        GetInstanceEnvironmentRequest,
        GetInstanceEnvironmentResult,
        PollContainerHealthRequest,
        PollContainerHealthResult,
        PublishMCPEventRequest,
        PublishMCPEventResult,
        UpdateInstanceStatusRequest,
        UpdateInstanceStatusResult,
    )

    @activity.defn(name="update_mcp_instance_status_activity")
    async def update_mcp_instance_status_activity(
        request: UpdateInstanceStatusRequest,
    ) -> UpdateInstanceStatusResult:
        """Update MCP instance status in the database."""
        from agentarea_common.auth.context import UserContext
        from agentarea_common.config import get_database

        from agentarea_mcp.domain.auth_models import (
            MCPAuthConfig,  # noqa: F401 - register FK target
        )
        from agentarea_mcp.infrastructure.repository import (
            MCPServerInstanceRepository,
        )

        try:
            db = get_database()
            async with db.async_session_factory() as session:
                user_context = UserContext(
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                )
                repo = MCPServerInstanceRepository(session, user_context)

                update_kwargs: dict[str, Any] = {"status": request.status}

                if request.json_spec_patch:
                    instance = await repo.get_by_id(request.instance_id)
                    if instance:
                        merged_spec = dict(instance.json_spec or {})
                        merged_spec.update(request.json_spec_patch)
                        update_kwargs["json_spec"] = merged_spec

                result = await repo.update(request.instance_id, **update_kwargs)
                await session.commit()

                return UpdateInstanceStatusResult(
                    success=result is not None,
                    error=None if result else "Instance not found",
                )
        except Exception as e:
            logger.error("Failed to update instance status: %s", e)
            return UpdateInstanceStatusResult(success=False, error=str(e))

    @activity.defn(name="create_mcp_container_activity")
    async def create_mcp_container_activity(
        request: CreateContainerRequest,
    ) -> CreateContainerResult:
        """Call Go MCP Manager POST /instances to create a container."""
        from agentarea_common.config import get_settings

        try:
            settings = get_settings()
            mcp_manager_url = settings.mcp.MCP_MANAGER_URL

            payload = {
                "instance_id": str(request.instance_id),
                "name": request.instance_name,
                "service_name": str(request.instance_id),
                "json_spec": request.json_spec,
                "workspace_id": request.workspace_id,
            }

            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{mcp_manager_url}/instances",
                    json=payload,
                )

                if resp.status_code in (200, 201, 409):
                    return CreateContainerResult(success=True)
                else:
                    error_msg = (
                        f"Go manager returned {resp.status_code}: {resp.text}"
                    )
                    logger.error(error_msg)
                    return CreateContainerResult(success=False, error=error_msg)

        except Exception as e:
            logger.error("Failed to create container: %s", e)
            return CreateContainerResult(success=False, error=str(e))

    @activity.defn(name="delete_mcp_container_activity")
    async def delete_mcp_container_activity(
        request: DeleteContainerRequest,
    ) -> DeleteContainerResult:
        """Call Go MCP Manager DELETE /instances/:id to stop a container."""
        from agentarea_common.config import get_settings

        try:
            settings = get_settings()
            mcp_manager_url = settings.mcp.MCP_MANAGER_URL

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.delete(
                    f"{mcp_manager_url}/instances/{request.instance_id}",
                )

                # 404 is acceptable — container may already be gone
                if resp.status_code in (200, 204, 404):
                    return DeleteContainerResult(success=True)
                else:
                    error_msg = (
                        f"Go manager returned {resp.status_code}: {resp.text}"
                    )
                    logger.error(error_msg)
                    return DeleteContainerResult(success=False, error=error_msg)

        except Exception as e:
            logger.error("Failed to delete container: %s", e)
            return DeleteContainerResult(success=False, error=str(e))

    @activity.defn(name="poll_mcp_container_health_activity")
    async def poll_mcp_container_health_activity(
        request: PollContainerHealthRequest,
    ) -> PollContainerHealthResult:
        """Single health check against Go MCP Manager."""
        from agentarea_common.config import get_settings

        try:
            settings = get_settings()
            mcp_manager_url = settings.mcp.MCP_MANAGER_URL

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{mcp_manager_url}/instances/{request.instance_id}/health",
                )

                if resp.status_code == 200:
                    data = resp.json()
                    return PollContainerHealthResult(
                        healthy=data.get("healthy", False),
                        status=data.get("status", "unknown"),
                    )
                elif resp.status_code == 503:
                    data = resp.json()
                    return PollContainerHealthResult(
                        healthy=False,
                        status=data.get("status", "unhealthy"),
                    )
                elif resp.status_code == 404:
                    return PollContainerHealthResult(
                        healthy=False,
                        status="not_found",
                    )
                else:
                    return PollContainerHealthResult(
                        healthy=False,
                        status="error",
                        error=f"Unexpected status code: {resp.status_code}",
                    )

        except Exception as e:
            logger.error("Health check failed: %s", e)
            return PollContainerHealthResult(
                healthy=False, status="error", error=str(e)
            )

    @activity.defn(name="discover_mcp_tools_activity")
    async def discover_mcp_tools_activity(
        request: DiscoverToolsRequest,
    ) -> DiscoverToolsResult:
        """Connect to running MCP server and discover tools.

        Resolves the container's direct IP:port from the Go manager health
        endpoint so we bypass Traefik (avoids host-header mismatches).
        Falls back to the Traefik gateway URL if the direct endpoint is
        unavailable.
        """
        from agentarea_common.config import get_settings

        try:
            settings = get_settings()

            # Resolve direct container URL from Go manager
            mcp_manager_url = settings.mcp.MCP_MANAGER_URL
            mcp_url = None
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(
                        f"{mcp_manager_url}/instances/{request.instance_id}/health",
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        details = data.get("details", {})
                        direct_endpoint = details.get("direct_http_endpoint")
                        if direct_endpoint:
                            mcp_url = f"{direct_endpoint}/mcp"
            except Exception as exc:
                logger.debug("Direct endpoint resolution failed: %s", exc)

            if not mcp_url:
                # Fallback to Traefik gateway
                gateway_url = settings.mcp.MCP_GATEWAY_URL
                mcp_url = f"{gateway_url}/mcp/{request.instance_name}/mcp"

            logger.info("Tool discovery connecting to %s", mcp_url)

            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(
                mcp_url, timeout=timedelta(seconds=15)
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()

            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema if t.inputSchema else {},
                }
                for t in result.tools
            ]

            logger.info(
                "Discovered %d tools for instance %s",
                len(tools),
                request.instance_id,
            )
            return DiscoverToolsResult(success=True, tools=tools)

        except Exception as e:
            logger.warning(
                "Tool discovery failed for %s: %s", request.instance_id, e
            )
            return DiscoverToolsResult(success=False, error=str(e))

    @activity.defn(name="publish_mcp_event_activity")
    async def publish_mcp_event_activity(
        request: PublishMCPEventRequest,
    ) -> PublishMCPEventResult:
        """Publish an MCP lifecycle event via the event broker (for SSE to frontend)."""
        from agentarea_common.events.base_events import DomainEvent
        from agentarea_common.events.router import create_event_broker_from_router

        try:
            # Convert RedisRouter → RedisEventBroker (same pattern as agent activities)
            redis_event_broker = create_event_broker_from_router(
                dependencies.event_broker
            )

            event_data = dict(request.event_data)
            event_data["instance_id"] = str(request.instance_id)
            event_data["workspace_id"] = request.workspace_id

            event = DomainEvent(
                event_type=request.event_type,
                aggregate_id=str(request.instance_id),
                aggregate_type="mcp_instance",
                original_event_type=request.event_type,
                original_data=event_data,
                **event_data,
            )
            await redis_event_broker.publish(event)
            return PublishMCPEventResult(success=True)
        except Exception as e:
            logger.warning("Failed to publish MCP event: %s", e)
            return PublishMCPEventResult(success=False, error=str(e))

    @activity.defn(name="get_mcp_instance_environment_activity")
    async def get_mcp_instance_environment_activity(
        request: GetInstanceEnvironmentRequest,
    ) -> GetInstanceEnvironmentResult:
        """Resolve environment variables from the secret manager for container startup."""
        from agentarea_common.auth.context import UserContext
        from agentarea_common.config import get_database

        from agentarea_mcp.application.mcp_env_service import (
            MCPEnvironmentService,
        )
        from agentarea_mcp.infrastructure.repository import (
            MCPServerInstanceRepository,
        )

        try:
            db = get_database()
            async with db.async_session_factory() as session:
                user_context = UserContext(
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                )
                repo = MCPServerInstanceRepository(session, user_context)
                instance = await repo.get_by_id(request.instance_id)

                if not instance:
                    return GetInstanceEnvironmentResult(
                        error="Instance not found"
                    )

                env_var_names = instance.get_configured_env_vars()
                if not env_var_names:
                    return GetInstanceEnvironmentResult()

                secret_manager = dependencies.secret_manager_factory.create(
                    session=session, user_context=user_context
                )
                env_service = MCPEnvironmentService(secret_manager)
                env_vars = await env_service.get_instance_environment(
                    request.instance_id, env_var_names
                )

                return GetInstanceEnvironmentResult(env_vars=env_vars)

        except Exception as e:
            logger.error("Failed to resolve environment: %s", e)
            return GetInstanceEnvironmentResult(error=str(e))

    return [
        update_mcp_instance_status_activity,
        create_mcp_container_activity,
        delete_mcp_container_activity,
        poll_mcp_container_health_activity,
        discover_mcp_tools_activity,
        publish_mcp_event_activity,
        get_mcp_instance_environment_activity,
    ]
