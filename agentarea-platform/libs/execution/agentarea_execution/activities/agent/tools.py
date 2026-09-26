"""Capability tool calls (MCP, OpenAPI, platform toolsets) and their payments."""

import itertools
import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_agents_sdk import ToolExecutor
from agentarea_agents_sdk.tools.invocation_context import ToolInvocationContext
from agentarea_agents_sdk.tools.tool_builders import allowed_tool_names
from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    ToolAuthorizationRequest,
    authorize_tool_invocation,
)
from agentarea_common.money import ZERO, serialize_money, to_money
from agentarea_wallet.domain.enums import settlement_status
from prometheus_client import Counter
from temporalio import activity

from ...interfaces import ActivityDependencies
from ...models import MCPToolRequest, MCPToolResult, McpToolRoute
from ..heartbeat import auto_heartbeater
from .sandbox import agent_artifact_actor, sandbox_control_auth_secret, sandbox_file_auth_secret

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


def _mcp_attachment(tools: list[dict[str, Any]] | None, attachment_ref: str) -> dict | None:
    """The agent's MCP attachment that references its server as ``attachment_ref``."""
    return next(
        (
            tool
            for tool in tools or []
            if isinstance(tool, dict)
            and tool.get("type") == "mcp"
            and str(tool.get("name")) == attachment_ref
        ),
        None,
    )


def mcp_route_denial(tools: list[dict[str, Any]] | None, route: McpToolRoute) -> str | None:
    """Why the agent may not call this routed MCP tool, or ``None`` when it may."""
    attachment = _mcp_attachment(tools, route.attachment_ref)
    if attachment is None:
        return "its MCP server is not attached to this agent"
    enabled = allowed_tool_names(attachment.get("settings") or {})
    if enabled is not None and route.raw_name not in enabled:
        return "the tool is not enabled for this agent"
    return None


def _deny_tool_result(tool_name: str, reason: str) -> MCPToolResult:
    return MCPToolResult(
        success=False,
        result=f"Tool call denied by policy: {reason}",
        execution_time="",
        error=reason,
    )


_mcp_dispatch_failed_total = Counter(
    "mcp_dispatch_failed_total",
    "Number of MCP dispatch failures",
    ["reason"],
)


def _payment_call_ref(request: MCPToolRequest) -> str:
    """Identify the tool call a payment belongs to, identically on every retry of the activity."""
    if request.task_id and request.tool_call_id:
        return f"{request.task_id}:{request.tool_call_id}"
    info = activity.info()
    return f"{info.workflow_id}:{info.workflow_run_id}:{info.activity_id}"


def _activity_output_id(prefix: str) -> str:
    """Return a stable-ish output id for the current activity attempt."""
    try:
        raw = activity.info().activity_id
    except Exception:
        raw = prefix
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)
    return f"{prefix}_{safe}"


def _server_icon_from_instance(instance: Any) -> str | None:
    """Best-effort icon URL for an MCP server instance.

    Returns the first ``src`` from ``instance.json_spec["icons"]`` when it is a
    non-empty list of dicts, else None. Guards a missing/None json_spec.
    """
    json_spec = getattr(instance, "json_spec", None)
    if not isinstance(json_spec, dict):
        return None
    icons = json_spec.get("icons")
    if not isinstance(icons, list) or not icons:
        return None
    first = icons[0]
    if isinstance(first, dict):
        src = first.get("src")
        return src if isinstance(src, str) else None
    return None


async def _offload_large_activity_output(
    *,
    workspace_id: str | None,
    task_id: str | None,
    output_id: str,
    content: str,
) -> str:
    """Offload large activity payloads before they become Temporal history."""
    from agentarea_execution.workflows.constants import TOOL_OUTPUT_OFFLOAD_CHARS
    from agentarea_execution.workflows.context_store import ContextStore
    from agentarea_execution.workflows.helpers import build_output_summary

    if not content or len(content) <= TOOL_OUTPUT_OFFLOAD_CHARS or not workspace_id or not task_id:
        return content

    try:
        store = ContextStore(str(workspace_id), str(task_id))
        await store.store_output(output_id, content)
        return build_output_summary(content, output_id)
    except Exception as exc:
        logger.warning("Activity output offload failed for %s: %s", output_id, exc, exc_info=True)
        head = content[:TOOL_OUTPUT_OFFLOAD_CHARS]
        return (
            f"{head}\n... [activity output truncated at {TOOL_OUTPUT_OFFLOAD_CHARS} chars; "
            f"offload failed: {exc}]"
        )


def make_tools_activities(
    dependencies: ActivityDependencies, container: "ActivityServiceContainer"
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext, create_user_context

    @activity.defn
    @auto_heartbeater
    async def execute_mcp_tool_activity(
        request: MCPToolRequest,
    ) -> MCPToolResult:
        """Execute an MCP tool or built-in tool."""
        decision = await authorize_tool_invocation(
            ToolAuthorizationRequest(
                tool_name=request.tool_name,
                tool_args=request.tool_args,
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                effective_policy=request.effective_policy,
                aliases=request.mcp_route.policy_names(request.tool_name)
                if request.mcp_route
                else (),
            )
        )
        if decision.action is ToolAuthorizationAction.REQUIRE_APPROVAL:
            return _deny_tool_result(
                request.tool_name,
                f"{decision.reason}; approval must be resolved before activity execution",
            )
        if not decision.allowed:
            return _deny_tool_result(request.tool_name, decision.reason)

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            mcp_server_instance_service = await ctx.get_mcp_server_instance_service()

            # Create tool executor with properly configured code tools
            from agentarea_agents_sdk.tools.code_tools_loader import create_code_tool_instance
            from agentarea_agents_sdk.tools.decorator_tool import Toolset, ToolsetAdapter

            tool_executor = ToolExecutor()

            # Register code tools from configuration (new schema)
            if request.tools and isinstance(request.tools, list):
                for tool_config in request.tools:
                    if not isinstance(tool_config, dict):
                        continue

                    # Only process code tools here
                    if tool_config.get("type") != "code":
                        continue

                    tool_name = tool_config.get("name")
                    if not tool_name:
                        continue

                    # Extract settings
                    settings = tool_config.get("settings", {})
                    disabled_methods = settings.get("disabled_methods", [])

                    # Convert disabled_methods to constructor arguments
                    toolset_methods = (
                        dict.fromkeys(disabled_methods, False) if disabled_methods else {}
                    )

                    # Build runtime kwargs for tools that need request context.
                    extra_kwargs: dict = {}
                    if tool_name in ("agentarea/files", "agentarea/workspace_files"):
                        # The file tool must write to the same filesystem bash
                        # (agentarea/shell) runs in, so code the agent saves is
                        # visible to the commands it runs. SandboxFileStore
                        # targets the pod /workspace via the control-plane
                        # sandbox file API instead of the S3 task workspace bash
                        # cannot see. No workspace_repository is passed, so
                        # FileToolset resolves against self.storage.
                        from agentarea_agents_sdk.tools.sandbox_file_store import SandboxFileStore

                        extra_kwargs = {
                            "storage": SandboxFileStore(
                                mcp_manager_url=dependencies.settings.mcp.MCP_MANAGER_URL,
                                workspace_id=str(request.workspace_id),
                                task_id=str(request.task_id) if request.task_id else "",
                                auth_secret=sandbox_file_auth_secret(dependencies),
                            ),
                            "workspace_id": str(request.workspace_id),
                        }
                        if tool_name == "agentarea/workspace_files":
                            from agentarea_common.workspaces.lookup import workspace_slug_for

                            extra_kwargs["workspace_slug"] = await workspace_slug_for(
                                str(request.workspace_id)
                            )
                    elif tool_name == "agentarea/context":
                        # Read-only access to the org context store (tier 1).
                        # ArtifactService is workspace-scoped, so the task can
                        # only read its own workspace's org context. No recorder
                        # is wired because this tool never writes.
                        from agentarea_common.artifacts import ArtifactService

                        extra_kwargs = {
                            "storage": ArtifactService(),
                            "workspace_id": str(request.workspace_id),
                        }
                    elif tool_name == "agentarea/web":
                        # Web downloads must land on the SAME sandbox filesystem
                        # bash runs in (via SandboxFileStore), not durable-only,
                        # so a binary the agent fetches is visible to the shell
                        # commands it runs next. Durable write-through keeps it
                        # retrievable through the /files API. Mirrors agentarea/files.
                        from agentarea_agents_sdk.tools.sandbox_file_store import SandboxFileStore

                        extra_kwargs = {
                            "storage": SandboxFileStore(
                                mcp_manager_url=dependencies.settings.mcp.MCP_MANAGER_URL,
                                workspace_id=str(request.workspace_id),
                                task_id=str(request.task_id) if request.task_id else "",
                                auth_secret=sandbox_file_auth_secret(dependencies),
                            ),
                            "workspace_id": str(request.workspace_id),
                            "task_id": str(request.task_id) if request.task_id else "",
                            "search_base_url": (dependencies.settings.app.WEB_SEARCH_BASE_URL),
                            "fetch_base_url": (dependencies.settings.app.WEB_FETCH_BASE_URL),
                        }
                    elif tool_name == "agentarea/triggers":
                        # The triggers tool defaults agent_id/workspace_id/user_id to
                        # the calling task so the LLM never has to know its own id.
                        extra_kwargs = {
                            "default_agent_id": str(request.agent_id),
                            "default_workspace_id": str(request.workspace_id),
                            "default_user_id": str(user_context.user_id),
                            "event_broker": dependencies.event_broker,
                        }
                    elif tool_name == "agentarea/shell":
                        # The shell tool routes bash commands to the sandbox
                        # and needs to know which task it's running for.
                        # The activity is the only seam that has access to
                        # the Temporal context, so we build a typed
                        # ToolInvocationContext here and inject it; the
                        # toolset reads ctx.workflow_id without needing to
                        # know anything about Temporal.
                        try:
                            wf_id = activity.info().workflow_id
                        except Exception:
                            wf_id = ""
                        from agentarea_common.artifacts import (
                            DbArtifactEventRecorder,
                            WorkspaceRepository,
                        )

                        extra_kwargs = {
                            "mcp_manager_url": dependencies.settings.mcp.MCP_MANAGER_URL,
                            "auth_secret": sandbox_control_auth_secret(dependencies),
                            "ctx": ToolInvocationContext(
                                workflow_id=wf_id or "",
                                task_id=str(request.task_id) if request.task_id else "",
                                workspace_id=str(request.workspace_id),
                                user_id=str(user_context.user_id),
                                agent_id=str(request.agent_id),
                                metadata={
                                    str(k): str(v)
                                    for k, v in (request.metadata or {}).items()
                                    if v is not None
                                },
                            ),
                            "workspace_repository": WorkspaceRepository(
                                recorder=DbArtifactEventRecorder(),
                                actor=agent_artifact_actor(request, user_context),
                            ),
                            "workspace_id": str(request.workspace_id),
                            "task_id": str(request.task_id) if request.task_id else "",
                        }

                    # Create and register the code tool instance
                    tool_instance = create_code_tool_instance(
                        tool_name, toolset_methods, extra_kwargs=extra_kwargs
                    )
                    if tool_instance:
                        # Check if tool is a Toolset - if so, wrap it in adapter for compatibility
                        if isinstance(tool_instance, Toolset):
                            tool_instance = ToolsetAdapter(tool_instance)

                        tool_executor.register_tool(tool_instance)
                        logger.info(f"Registered code tool for execution: {tool_name}")
                    else:
                        logger.warning(f"Unknown code tool requested: {tool_name}")

            payment_handler: Callable[..., Awaitable[dict[str, Any] | None]] | None = None

            payment_sequence = itertools.count()

            def next_payment_key() -> str:
                from ..payment_handler import payment_idempotency_key

                return payment_idempotency_key(_payment_call_ref(request), next(payment_sequence))

            async def find_settled_payment(
                wallet_service: Any, idempotency_key: str
            ) -> dict[str, Any] | None:
                record = await wallet_service.find_settled_payment(idempotency_key)
                if record is None:
                    return None
                logger.warning(
                    "Payment %s already settled for tool call %s; not paying again",
                    idempotency_key,
                    request.tool_call_id,
                )
                return {
                    "success": False,
                    "already_settled": True,
                    "protocol": record.protocol,
                    "amount_usd": serialize_money(record.amount_usd),
                    "recipient": record.recipient,
                    "tx_hash": record.tx_hash,
                    "protocol_metadata": record.protocol_metadata or {},
                    "idempotency_key": idempotency_key,
                    "error": (
                        f"This request was already paid (tx {record.tx_hash}) by an earlier "
                        "attempt of the same tool call; not paying again"
                    ),
                }

            async def get_payment_context() -> tuple[Any, Any, dict[str, Any], str, Decimal] | None:
                return None

            if request.agent_id:
                agent_id = request.agent_id

                async def get_payment_context() -> (
                    tuple[Any, Any, dict[str, Any], str, Decimal] | None
                ):
                    try:
                        wallet_service = await ctx.get_wallet_service()
                        wallet = await wallet_service.get_wallet(agent_id)
                    except Exception as e:
                        logger.debug("No active wallet for payment handling: %s", e, exc_info=True)
                        return None

                    if getattr(wallet, "status", None) != "active":
                        return None

                    credentials = await wallet_service.get_wallet_credentials(wallet)
                    wallet_config = {
                        "wallet_type": wallet.wallet_type,
                        "x402_config": wallet.x402_config,
                        "mpp_config": wallet.mpp_config,
                        "x402_private_key": credentials.get("x402_private_key"),
                        "mpp_tempo_key": credentials.get("mpp_tempo_key"),
                    }
                    execution_id = request.execution_id or request.task_id or ""
                    budget_remaining = await wallet_service.get_service_budget_remaining(
                        agent_id, execution_id
                    )
                    return wallet_service, wallet, wallet_config, execution_id, budget_remaining

                async def record_payment_result(
                    payment_context: tuple[Any, Any, dict[str, Any], str, Decimal] | None,
                    result: dict[str, Any] | None,
                    *,
                    tool_name: str,
                    idempotency_key: str,
                ) -> None:
                    if not payment_context or not result or result.get("already_settled"):
                        return
                    if result.get("protocol") not in {"x402", "mpp"}:
                        return
                    amount = to_money(result.get("amount_usd"))
                    if amount <= ZERO:
                        return
                    wallet_service, wallet, _, execution_id, _ = payment_context
                    await wallet_service.record_payment(
                        wallet_id=wallet.id,
                        agent_id=str(request.agent_id),
                        execution_id=execution_id,
                        protocol=str(result.get("protocol")),
                        amount_usd=amount,
                        recipient=str(result.get("recipient") or ""),
                        tx_hash=result.get("tx_hash"),
                        tool_name=tool_name,
                        tool_call_id=request.tool_call_id or "",
                        idempotency_key=idempotency_key,
                        status=settlement_status(
                            request_succeeded=bool(result.get("success")),
                            tx_hash=result.get("tx_hash"),
                        ),
                        error_message=result.get("error"),
                        protocol_metadata=result.get("protocol_metadata"),
                    )

                async def _payment_handler(**payment_kwargs: Any) -> dict[str, Any] | None:
                    """Handle HTTP 402 for paid HTTP-backed tools using the calling agent wallet."""
                    payment_context = await get_payment_context()
                    if not payment_context:
                        return None
                    wallet_service, _, wallet_config, _, budget_remaining = payment_context
                    idempotency_key = next_payment_key()
                    settled = await find_settled_payment(wallet_service, idempotency_key)
                    if settled is not None:
                        return settled

                    from ..payment_handler import handle_402_payment

                    result = await handle_402_payment(
                        url=payment_kwargs["url"],
                        method=payment_kwargs["method"],
                        request_headers=payment_kwargs.get("request_headers") or {},
                        request_body=payment_kwargs.get("request_body"),
                        response_status=payment_kwargs["response_status"],
                        response_headers=payment_kwargs.get("response_headers") or {},
                        response_body=payment_kwargs.get("response_body") or "",
                        wallet_config=wallet_config,
                        budget_remaining=budget_remaining,
                        idempotency_key=idempotency_key,
                    )

                    await record_payment_result(
                        payment_context,
                        result,
                        tool_name=str(payment_kwargs.get("tool_name") or request.tool_name),
                        idempotency_key=idempotency_key,
                    )
                    return result

                payment_handler = _payment_handler

            # Register agent tools from configuration
            if request.tools and isinstance(request.tools, list):
                agent_configs = [
                    tc for tc in request.tools if isinstance(tc, dict) and tc.get("type") == "agent"
                ]
                if agent_configs:
                    base_url = f"{dependencies.settings.app.API_BASE_URL}/api/v1"
                    agent_service = await ctx.get_agent_service()

                    # Create task service for internal delegation
                    from agentarea_agents_sdk.tools.agent_delegation_tool import (
                        create_task_service_for_delegation,
                    )
                    from agentarea_common.config import get_database

                    delegation_session = get_database().async_session_factory()
                    ctx._sessions.append(delegation_session)

                    delegation_task_service = create_task_service_for_delegation(
                        session=delegation_session,
                        user_context=user_context,
                        event_broker=dependencies.event_broker,
                    )

                    from agentarea_agents_sdk.tools.agent_tool_factory import AgentToolFactory

                    for tool_config in agent_configs:
                        agent_name = tool_config.get("name")
                        if not agent_name:
                            continue

                        delegation_tool = await AgentToolFactory.create_tool(
                            agent_name=agent_name,
                            agent_service=agent_service,
                            base_url=base_url,
                            a2a_url_override=(tool_config.get("settings") or {}).get("a2a_url"),
                            task_service=delegation_task_service,
                            workspace_id=request.workspace_id,
                            user_id=user_context.user_id,
                            payment_handler=payment_handler,
                        )
                        if delegation_tool:
                            tool_executor.register_tool(delegation_tool)
                            logger.info(f"Registered agent tool for execution: {agent_name}")

            # Register OpenAPI tools from configuration. Each connection expands to one
            # or more OpenAPITool instances (one per allowed operation), which are then
            # findable by name in the executor's registry — the same way code and agent
            # tools are pre-registered.
            if request.tools and isinstance(request.tools, list):
                openapi_configs = [
                    tc
                    for tc in request.tools
                    if isinstance(tc, dict) and tc.get("type") == "openapi"
                ]
                if openapi_configs:
                    from agentarea_agents_sdk.tools.openapi_tool import OpenAPIToolFactory

                    openapi_connection_service = await ctx.get_openapi_connection_service()
                    for tool_config in openapi_configs:
                        settings = tool_config.get("settings") or {}
                        # Prefer settings.openapi_connection_id (stable UUID) over tool.name.
                        connection_ref = settings.get("openapi_connection_id") or tool_config.get(
                            "name"
                        )
                        if not connection_ref:
                            logger.warning("Skipping openapi tool with no connection reference")
                            continue
                        raw_allowed = settings.get("allowed_tools") or []
                        allowed_names = [
                            (t["tool_name"] if isinstance(t, dict) else t) for t in raw_allowed
                        ]
                        openapi_tools = await OpenAPIToolFactory.create_tools_from_connection(
                            connection_name_or_id=connection_ref,
                            allowed_tools=allowed_names,
                            openapi_connection_service=openapi_connection_service,
                            payment_handler=payment_handler,
                        )
                        for openapi_tool_instance in openapi_tools:
                            tool_executor.register_tool(openapi_tool_instance)
                            logger.info(
                                f"Registered openapi tool for execution: {openapi_tool_instance.name} "
                                f"(connection={connection_ref})"
                            )

            # MCP dispatch: the workflow resolved the model-facing name to one
            # attached server and the raw name it advertises. The call goes to that
            # server only, and only for a tool the agent's attachment enables.
            route = request.mcp_route
            if route is not None:
                denial = mcp_route_denial(request.tools, route)
                if denial is not None:
                    return _deny_tool_result(request.tool_name, denial)
                instance = await mcp_server_instance_service.get(UUID(route.instance_id))
                if instance is None:
                    return MCPToolResult(
                        success=False,
                        result=f"MCP server instance {route.instance_id} no longer exists",
                        execution_time="",
                        error=f"MCP server instance {route.instance_id} not found",
                        source="mcp",
                        server_instance_id=route.instance_id,
                    )

                payment_httpx_client_factory = None
                mcp_payments: list[dict[str, Any]] = []
                if request.agent_id:
                    payment_context = await get_payment_context()
                    if payment_context:
                        from ..mcp_payment_httpx import create_payment_httpx_client_factory

                        wallet_service, _, wallet_config, _, budget_remaining = payment_context

                        async def find_settled_mcp_payment(
                            idempotency_key: str, *, wallet_service=wallet_service
                        ) -> dict[str, Any] | None:
                            return await find_settled_payment(wallet_service, idempotency_key)

                        async def on_mcp_payment(
                            result: dict[str, Any],
                            *,
                            payment_context=payment_context,
                            mcp_payments=mcp_payments,
                            tool_name=request.tool_name,
                        ) -> None:
                            mcp_payments.append(result)
                            await record_payment_result(
                                payment_context,
                                result,
                                tool_name=tool_name,
                                idempotency_key=result["idempotency_key"],
                            )

                        payment_httpx_client_factory = create_payment_httpx_client_factory(
                            wallet_config=wallet_config,
                            budget_remaining=budget_remaining,
                            next_idempotency_key=next_payment_key,
                            find_settled_payment=find_settled_mcp_payment,
                            on_payment=on_mcp_payment,
                        )

                try:
                    mcp_result = await mcp_server_instance_service.execute_tool(
                        UUID(str(instance.id)),
                        route.raw_name,
                        request.tool_args,
                        httpx_client_factory=payment_httpx_client_factory,
                    )
                except Exception as e:
                    logger.error("MCP tool execution failed: %s", e, exc_info=True)
                    _mcp_dispatch_failed_total.labels(reason=type(e).__name__).inc()
                    return MCPToolResult(
                        success=False,
                        result=f"MCP tool error: {type(e).__name__}: {e}",
                        execution_time="",
                        error=str(e),
                        source="mcp",
                        server_instance_id=str(instance.id),
                        server_name=getattr(instance, "name", None),
                        server_icon=_server_icon_from_instance(instance),
                    )

                result_text = await _offload_large_activity_output(
                    workspace_id=request.workspace_id,
                    task_id=request.task_id,
                    output_id=_activity_output_id("mcp_tool"),
                    content=str(mcp_result.get("result") or ""),
                )
                return MCPToolResult(
                    success=bool(mcp_result.get("success", False)),
                    result=result_text,
                    execution_time="",
                    error=mcp_result.get("error"),
                    service_cost=sum(
                        (to_money(p.get("amount_usd")) for p in mcp_payments if p.get("success")),
                        ZERO,
                    ),
                    payment=(
                        {"payments": mcp_payments}
                        if len(mcp_payments) > 1
                        else (mcp_payments[0] if mcp_payments else None)
                    ),
                    source="mcp",
                    server_instance_id=str(instance.id),
                    server_name=getattr(instance, "name", None),
                    server_icon=_server_icon_from_instance(instance),
                )

            try:
                from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context

                with use_mcp_user_context(user_context):
                    result = await tool_executor.execute_tool(
                        tool_name=request.tool_name,
                        tool_args=request.tool_args,
                        server_instance_id=request.server_instance_id,
                        mcp_server_instance_service=mcp_server_instance_service,
                    )

                result_text = await _offload_large_activity_output(
                    workspace_id=request.workspace_id,
                    task_id=request.task_id,
                    output_id=_activity_output_id("tool"),
                    content=str(result.get("result") or ""),
                )
                server_instance_id = result.get("server_instance_id")
                # OpenAPI tools may self-declare source; otherwise infer from
                # whether the tool resolved against an MCP server instance.
                source = result.get("source") or ("mcp" if server_instance_id else "builtin")
                return MCPToolResult(
                    success=result.get("success", False),
                    result=result_text,
                    execution_time=str(result.get("execution_time") or ""),
                    error=result.get("error"),
                    exit_code=result.get("exit_code"),
                    outcome=result.get("outcome"),
                    artifact_paths=[str(p) for p in (result.get("artifact_paths") or [])],
                    service_cost=to_money(result.get("service_cost")),
                    payment=result.get("payment")
                    if isinstance(result.get("payment"), dict)
                    else None,
                    source=source,
                    server_instance_id=str(server_instance_id) if server_instance_id else None,
                    server_name=result.get("server_name"),
                    server_icon=result.get("server_icon"),
                )

            except Exception as e:
                logger.error("Tool execution failed: %s", e, exc_info=True)
                _mcp_dispatch_failed_total.labels(reason=type(e).__name__).inc()
                return MCPToolResult(
                    success=False,
                    result=f"MCP tool error: {type(e).__name__}: {e}",
                    execution_time="",
                    error=str(e),
                    source="builtin",
                )

    return [
        execute_mcp_tool_activity,
    ]
