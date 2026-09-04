"""MCP instance activities for Temporal workers.

Lifecycle activities (create/delete/poll_health) removed — replaced by verify().

Remaining activities:
  1. discover_mcp_tools           — plain async helper; container-backed
                                    discovery goes through the manager gateway
  2. discover_mcp_tools_activity  — Temporal-wrapped version
  3. get_mcp_instance_environment_activity
  4. resolve_auth_headers_activity
  5. update_mcp_instance_status_activity
  6. publish_mcp_event_activity
"""

import logging
from datetime import timedelta
from typing import Any

from agentarea_execution.interfaces import ActivityDependencies
from temporalio import activity

from agentarea_mcp.tool_serialization import serialize_mcp_tool

logger = logging.getLogger(__name__)


async def discover_mcp_tools(
    endpoint_url: str | None = None,
    instance_id: str | None = None,
    instance_name: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
    transport: str | None = None,
) -> list[dict]:
    """Connect to a running MCP server and list tools.

    Plain async function — importable by verify() and any other non-Temporal caller.
    Transport selection is delegated to the shared ``mcp_transport_candidates``
    (single source of truth) so remote servers that serve streamable-HTTP at the
    root (e.g. Vercel) are hit at the URL as-given, not re-suffixed to /mcp or /sse.

    Args:
        endpoint_url: Direct URL — url-type MCP servers only. Container-backed
            servers have no direct address; pass instance_id instead.
        instance_id: Instance UUID string, reached through the manager gateway.
        instance_name: Unused for addressing; retained for logging by callers.
        headers: Extra request headers (e.g. auth).
        timeout: Per-attempt connection timeout in seconds.
        transport: Declared MCP wire transport ("streamable-http"|"sse"); when set,
            it is honored exactly with no probing.

    Returns:
        List of tool dicts with keys: name, description, inputSchema.

    Raises:
        Exception on any connection or protocol error.
    """
    from agentarea_common.config import get_settings

    from agentarea_mcp.verification import mcp_transport_candidates

    settings = get_settings()
    custom_headers: dict[str, str] = dict(headers) if headers else {}

    if endpoint_url:
        # Do NOT pre-append /mcp — let the shared resolver honor the URL as-given
        # (bare root, /mcp, or /sse) so root-streamable remotes aren't broken.
        base_url = endpoint_url.rstrip("/")
    elif instance_id:
        # Container-backed discovery is an ordinary request through the manager
        # gateway, exactly like verification and agent tool calls.
        #
        # This used to ask the manager for `direct_http_endpoint` and dial the
        # workload address, falling back to a retired Traefik path. Both routes
        # skipped the gateway that starts the workload on demand, holds a
        # request lease for the call, and reaps it when idle — so discovery
        # could hit a workload nothing was keeping alive, or one already gone.
        base_url = settings.mcp.manager_gateway_url(instance_id)
        custom_headers.update(settings.mcp.manager_gateway_headers())
    else:
        raise ValueError(
            "tool discovery needs endpoint_url for a URL-type MCP server, "
            "or instance_id to reach a container-backed one through the gateway"
        )

    logger.info("Tool discovery connecting to %s", base_url)

    from mcp import ClientSession

    streamable_urls, sse_url = mcp_transport_candidates(base_url, transport)

    result = None
    last_err: BaseException | None = None
    for streamable_url in streamable_urls:
        try:
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(
                streamable_url,
                timeout=timedelta(seconds=timeout),
                headers=custom_headers or None,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as sess:
                    await sess.initialize()
                    result = await sess.list_tools()
            break
        except Exception as transport_err:
            last_err = transport_err
            logger.info(
                "Streamable HTTP failed for %s (%s), trying next transport",
                streamable_url,
                transport_err,
            )

    if result is None and sse_url is not None:
        from mcp.client.sse import sse_client

        async with sse_client(
            sse_url,
            timeout=timeout,
            headers=custom_headers or None,
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as sess:
                await sess.initialize()
                result = await sess.list_tools()

    if result is None:
        raise last_err or RuntimeError(f"No usable MCP transport for {base_url}")

    tools = [serialize_mcp_tool(t) for t in result.tools]

    if instance_id:
        logger.info("Discovered %d tools for instance %s", len(tools), instance_id)
    return tools


def make_mcp_activities(dependencies: ActivityDependencies) -> list:
    """Factory function to create MCP activities for Temporal worker registration."""
    from agentarea_mcp.workflows.models import (
        DiscoverToolsRequest,
        DiscoverToolsResult,
        GetInstanceEnvironmentRequest,
        GetInstanceEnvironmentResult,
        PublishMCPEventRequest,
        PublishMCPEventResult,
        ResolveAuthHeadersRequest,
        ResolveAuthHeadersResult,
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

        from agentarea_mcp.domain import auth_models
        from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository

        _ = auth_models.MCPAuthConfig

        try:
            db = get_database()
            async with db.async_session_factory() as session:
                user_context = UserContext(
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                )
                repo = MCPServerInstanceRepository(session, user_context)

                update_kwargs: dict[str, Any] = {}
                if request.json_spec_patch:
                    instance = await repo.get_by_id(request.instance_id)
                    if instance:
                        merged_spec = dict(instance.json_spec or {})
                        merged_spec.update(request.json_spec_patch)
                        update_kwargs["json_spec"] = merged_spec

                if update_kwargs:
                    result = await repo.update(request.instance_id, **update_kwargs)
                    await session.commit()
                    return UpdateInstanceStatusResult(
                        success=result is not None,
                        error=None if result else "Instance not found",
                    )

                return UpdateInstanceStatusResult(success=True)
        except Exception as e:
            logger.error("Failed to update instance: %s", e)
            return UpdateInstanceStatusResult(success=False, error=str(e))

    @activity.defn(name="discover_mcp_tools_activity")
    async def discover_mcp_tools_activity(
        request: DiscoverToolsRequest,
    ) -> DiscoverToolsResult:
        """Temporal-wrapped tool discovery — delegates to discover_mcp_tools()."""
        try:
            tools = await discover_mcp_tools(
                endpoint_url=request.endpoint_url,
                instance_id=str(request.instance_id) if request.instance_id else None,
                instance_name=request.instance_name,
                headers=dict(request.headers) if request.headers else None,
            )
            return DiscoverToolsResult(success=True, tools=tools)
        except Exception as e:
            logger.warning("Tool discovery failed for %s: %s", request.instance_id, e)
            return DiscoverToolsResult(success=False, error=str(e))

    @activity.defn(name="publish_mcp_event_activity")
    async def publish_mcp_event_activity(
        request: PublishMCPEventRequest,
    ) -> PublishMCPEventResult:
        """Publish an MCP lifecycle event via the event broker."""
        from agentarea_common.events.base_events import DomainEvent

        try:
            redis_event_broker = dependencies.event_broker

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

        from agentarea_mcp.application.mcp_env_service import MCPEnvironmentService
        from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository

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
                    return GetInstanceEnvironmentResult(error="Instance not found")

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

    @activity.defn(name="resolve_auth_headers_activity")
    async def resolve_auth_headers_activity(
        request: ResolveAuthHeadersRequest,
    ) -> ResolveAuthHeadersResult:
        """Resolve authentication headers for an MCP instance's auth config."""
        from agentarea_common.auth.context import UserContext
        from agentarea_common.config import get_database

        from agentarea_mcp.application.auth_service import MCPAuthService
        from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository
        from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository

        try:
            db = get_database()
            async with db.async_session_factory() as session:
                user_context = UserContext(
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                )

                instance_repo = MCPServerInstanceRepository(session, user_context)
                instance = await instance_repo.get_by_id(request.instance_id)
                if not instance or not instance.auth_config_id:
                    return ResolveAuthHeadersResult()

                auth_repo = MCPAuthConfigRepository(session, user_context)
                secret_manager = dependencies.secret_manager_factory.create(
                    session=session, user_context=user_context
                )
                auth_service = MCPAuthService(auth_repo, secret_manager)
                auth_config = await auth_service.get(instance.auth_config_id)
                if not auth_config:
                    return ResolveAuthHeadersResult(
                        error=f"Auth config {instance.auth_config_id} not found"
                    )

                headers = await auth_service.get_auth_headers(auth_config)
                await session.commit()
                return ResolveAuthHeadersResult(headers=headers)

        except Exception as e:
            logger.error("Failed to resolve auth headers: %s", e)
            return ResolveAuthHeadersResult(error=str(e))

    return [
        update_mcp_instance_status_activity,
        discover_mcp_tools_activity,
        publish_mcp_event_activity,
        get_mcp_instance_environment_activity,
        resolve_auth_headers_activity,
    ]
