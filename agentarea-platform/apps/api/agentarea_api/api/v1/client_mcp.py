"""Dynamically-scoped MCP endpoint for clients (agent-proxies).

A single MCP server is mounted at ``/mcp/clients`` and its session manager is
started once in the app lifespan. Each request carries a client id in the path
(``/mcp/clients/{client_id}``); a scope middleware stashes it in a ContextVar and
the ``list_tools`` / ``call_tool`` handlers resolve that client's attachments on
the fly: its MCP instances' tools (aggregated, each narrowed to the tools the
client allows), its platform toolsets (minus their disabled methods, run in the
client's workspace), and ``activate_skill`` over its skills.

Every tool the client carries is still governed by the workspace policy: the
caller's workspace+user policy is resolved with the resolver task snapshots use
and judged by the one tool PDP (``decide_tool_policy``). A tool the policy denies
is neither listed nor run, and every call's verdict is audited. A call the
policy holds for approval is recorded and answered with an approval link; the
client's retry with the same arguments runs it once a person approved it.

``/client-mcp/{client_id}`` is the previous address, still mounted so harnesses
configured against it keep working until they are re-installed.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from agentarea_agents_sdk.mcp_server import UnknownToolsetError, selected_tools
from agentarea_agents_sdk.mcp_server.auth import (
    PROTECTED_RESOURCE_SCOPE_KEY,
    use_mcp_user_context,
)
from agentarea_agents_sdk.tools.mcp_tool_identity import mcp_tool_target, qualify_mcp_tool_name
from agentarea_api.platform_mcp import client_platform_server
from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    ToolAuthorizationDecision,
    ToolAuthorizationRequest,
    decide_tool_policy,
)
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_execution.workflows.helpers import approvers_for_tool
from agentarea_governance.domain.tool_call_approvals import GateVerdict, ToolCallRequest
from agentarea_governance.tool_calls import (
    GovernedToolCall,
    PlatformFundedTool,
    PlatformToolUsage,
    ToolCallOutcome,
    Verdict,
    run_tool_call,
)
from agentarea_mcp.application.mcp_aggregator import AggregatedMember, MCPAggregatorProxy
from agentarea_mcp.application.tool_list_cache import RedisToolListCache
from agentarea_mcp.domain.client_models import ClientPlatformToolset
from agentarea_mcp.domain.metering import platform_funded_resource, reported_quantity
from agentarea_mcp.domain.transport import MCPTransport
from mcp.server import Server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentarea_common.auth.context import UserContext
    from agentarea_mcp.application.service import MCPServerInstanceService
    from agentarea_openapi.application.service import OpenAPIConnectionService
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_client_id_var: ContextVar[str | None] = ContextVar("client_mcp_client_id", default=None)


class ClientAccessDeniedError(Exception):
    """Raised when the authenticated principal lacks `use` on the target client."""


async def _authorize_client_access(user_ctx, client_id: str) -> None:
    """Enforce that the authenticated principal may use this client's bundle.

    A client-credentials principal (token subject IS the client) is trusted for
    its own bundle; any other principal must hold the `use` relation in the
    access-control graph. Raises ``ClientAccessDeniedError`` otherwise.
    """
    if getattr(user_ctx, "client_id", None) == client_id:
        return
    from agentarea_common.auth.permission import PermissionService
    from agentarea_common.di.container import resolve

    allowed = await resolve(PermissionService).check(user_ctx.user_id, "use", "client", client_id)
    if not allowed:
        raise ClientAccessDeniedError(client_id)


_tool_list_cache: RedisToolListCache | None = None


def _tool_cache() -> RedisToolListCache:
    """Process-wide cache handle (the client itself pools connections).

    ``settings.broker`` is whichever broker this deployment configured, so the
    Redis URL is read defensively — and refused loudly when absent rather than
    quietly pointed at localhost, which would look like a working cache while
    every aggregate paid the full round trip.
    """
    global _tool_list_cache
    if _tool_list_cache is None:
        from agentarea_common.config import get_settings

        redis_url = getattr(get_settings().broker, "REDIS_URL", None)
        if not redis_url:
            raise RuntimeError(
                "The client MCP tool-list cache requires a Redis broker (AGENTAREA_REDIS_URL)"
            )
        _tool_list_cache = RedisToolListCache(redis_url)
    return _tool_list_cache


@dataclass(frozen=True)
class ClientScope:
    """What one client's endpoint serves, and as whom it runs platform tools."""

    proxy: MCPAggregatorProxy
    skill_registry: dict
    # Names of the platform tools the client carries.
    platform_tools: frozenset[str]
    # The caller, acting in the client's workspace.
    user_context: UserContext
    # The caller's resolved workspace+user policy (``EffectivePolicy`` JSON).
    tool_policy: dict
    # How the caller appears in the audit trail.
    actor_type: str
    # The client the call came through, as an approval request names it.
    client_id: str | None = None
    client_name: str | None = None
    # The connections the client carries, by id: a call on a platform-managed one
    # is metered as its tool declares.
    instances: dict[str, Any] | None = None


def _platform_tools(client_id: str, attached: list[ClientPlatformToolset]) -> frozenset[str]:
    """Tool names of the client's platform toolsets, minus their disabled methods.

    A toolset the platform has since dropped is skipped, loudly, so the rest of
    the bundle keeps working; a dropped method left in ``disabled_methods`` is
    already off and needs no handling.
    """
    server = client_platform_server()
    selected: set[str] = set()
    for attachment in attached:
        try:
            toolset = server.resolve(attachment.toolset)
        except UnknownToolsetError:
            logger.error(
                "Client %s carries platform toolset %r, which is no longer served",
                client_id,
                attachment.toolset,
                exc_info=True,
            )
            continue
        disabled = [m for m in attachment.disabled_methods or [] if m in toolset.tools]
        selected |= server.select({toolset.name: disabled})
    return frozenset(selected)


async def _effective_tool_policy(session: AsyncSession, user_ctx: UserContext) -> dict:
    """The caller's workspace+user policy, resolved as for a task snapshot.

    A client is not an agent, so there is no agent layer: what governs its calls
    is exactly what governs the same caller anywhere else in the workspace —
    the same resolution the governed MCP proxy uses.
    """
    from agentarea_common.base.repository_factory import RepositoryFactory
    from agentarea_governance.application import GovernancePolicyResolver

    resolver = GovernancePolicyResolver(RepositoryFactory(session, user_ctx))
    effective = await resolver.resolve(
        workspace_id=user_ctx.workspace_id,
        user_id=user_ctx.user_id,
    )
    return effective.to_json_dict()


def _actor_type(principal, client_id: str) -> str:
    if principal.client_id == client_id:
        return "client"
    return "api_key" if principal.api_key_id else "user"


async def _resolve_client_scope(client_id: str) -> ClientScope | None:
    """Resolve what a client's endpoint serves; None when the client does not exist.

    The set is exactly the client's own attachments.
    """
    # The id is a path segment anyone can type. Only a UUID names a client;
    # anything else would reach the database and fail there, and that error's
    # text (the SQL and the caller's workspace list) would become the reply.
    # The canonical spelling is what the database and the ReBAC graph hold.
    try:
        client_id = str(UUID(client_id))
    except ValueError:
        return None

    from agentarea_agents_sdk.mcp_server.auth import get_mcp_user_context
    from agentarea_agents_sdk.skills.skill_catalog_builder import SkillEntry
    from agentarea_common.base.repository_factory import RepositoryFactory
    from agentarea_common.base.tenant_scope import workspace_scope
    from agentarea_common.config.database import get_database
    from agentarea_common.infrastructure.connection_manager import get_connection_manager
    from agentarea_common.workspaces.lookup import workspace_slug_for
    from agentarea_mcp.application.service import MCPServerInstanceService
    from agentarea_mcp.infrastructure.client_repository import ClientRepository
    from agentarea_secrets.secret_manager_factory import get_real_secret_manager

    principal = get_mcp_user_context()
    connection_manager = get_connection_manager()
    broker = await connection_manager.get_event_broker()

    async with get_database().read_session() as session:
        workspace_id = await ClientRepository.locate_workspace(
            session, client_id, principal.accessible_workspaces or []
        )
        if workspace_id is None:
            return None

        await _authorize_client_access(principal, client_id)

        # A client endpoint is itself a workspace reference. Enter it before
        # constructing workspace-scoped dependencies: secret managers may
        # capture the workspace id in their constructor.
        user_ctx = principal.enter(workspace_id, await workspace_slug_for(workspace_id))
        with workspace_scope(workspace_id):
            client_repo = ClientRepository(session, user_ctx)
            client = await client_repo.get_by_id(client_id)
            if client is None:
                return None
            repo_factory = RepositoryFactory(session, user_ctx)
            secret = get_real_secret_manager(session=session, user_context=user_ctx)

            links = (await client_repo.get_instance_links([client_id])).get(str(client_id), {})
            platform_toolsets = (await client_repo.get_platform_toolsets([client_id])).get(
                str(client_id), []
            )
            instances = {str(i.id): i for i in client.mcp_instances}
            skills = {str(s.id): s for s in client.skills}

            skill_registry = {
                s.name: SkillEntry(
                    name=s.name,
                    description=s.description or "",
                    content=s.content or "",
                    files=[],
                )
                for s in skills.values()
            }

            instance_service = MCPServerInstanceService(repo_factory, broker, secret)
            proxy = await _aggregate_instances(
                client.name,
                client.description or "",
                instance_service,
                list(instances.values()),
                links,
            )
            return ClientScope(
                proxy=proxy,
                skill_registry=skill_registry,
                platform_tools=_platform_tools(client_id, platform_toolsets),
                user_context=user_ctx,
                tool_policy=await _effective_tool_policy(session, user_ctx),
                actor_type=_actor_type(principal, client_id),
                client_id=client_id,
                client_name=client.name,
                instances=instances,
            )


async def _aggregate_instances(
    name: str,
    description: str,
    instance_service: MCPServerInstanceService,
    instances: list,
    links: dict,
) -> MCPAggregatorProxy:
    """One server over *instances*, each dialed with its resolved url and credentials.

    An instance whose address cannot be resolved is left out, loudly, so the
    rest keep working.
    """
    members: list[AggregatedMember] = []
    instance_urls: dict[str, str] = {}
    instance_names: dict[str, str] = {}
    instance_headers: dict[str, dict[str, str]] = {}
    for order, inst in enumerate(instances):
        iid = str(inst.id)
        full = await instance_service.repository.get_by_id(inst.id)
        if full is None:
            continue
        try:
            url, headers, transport = await instance_service._resolve_mcp_url_and_headers(full)
        except Exception:
            logger.exception("Failed to resolve MCP url for instance %s", iid)
            continue
        instance_urls[iid] = url
        instance_names[iid] = full.name
        if headers:
            instance_headers[iid] = headers
        link = links.get(iid)
        members.append(
            AggregatedMember(
                mcp_instance_id=iid,
                order=order,
                namespace_prefix=link.namespace_prefix if link else None,
                transport=transport,
                # The operator's address for a platform-managed connection is the
                # platform's own choice, not the member's.
                pinned=full.transport == MCPTransport.URL
                and full.managed_by != MANAGED_BY_PLATFORM,
                allowed_tools=(
                    frozenset(link.allowed_tools)
                    if link and link.allowed_tools is not None
                    else None
                ),
            )
        )
    return MCPAggregatorProxy(
        name,
        description,
        members,
        instance_urls,
        instance_names,
        instance_headers,
        tool_cache=_tool_cache(),
    )


def _policy_aliases(scope: ClientScope, tool_name: str) -> tuple[str, ...]:
    """The other names a policy rule may give one of the client's instance tools.

    The same names an agent's call to that tool answers to (see
    ``McpToolIdentity.policy_names``): the canonical ``mcp:<instance id>:<raw>``,
    the server referenced by name, the ``mcp__<server>__<raw>`` an agent calls it
    by, and the raw name the server advertises — so a rule written against an
    agent's use of the tool governs the client's use of it too.
    """
    if tool_name in scope.platform_tools:
        return ()
    owner = scope.proxy.owner_of(tool_name)
    if owner is None:
        return ()
    member, raw_name = owner
    instance_id = str(member.mcp_instance_id)
    names = [mcp_tool_target(instance_id, raw_name)]
    if instance_name := scope.proxy.instance_names.get(instance_id):
        names += [
            mcp_tool_target(instance_name, raw_name),
            qualify_mcp_tool_name(instance_name, raw_name),
        ]
    names.append(raw_name)
    return tuple(names)


def _client_tool_decision(
    scope: ClientScope, tool_name: str, restricting_aliases: Sequence[str] = ()
) -> ToolAuthorizationDecision:
    """The PDP's verdict on the client running ``tool_name``."""
    return decide_tool_policy(
        scope.tool_policy,
        tool_name,
        aliases=_policy_aliases(scope, tool_name),
        restricting_aliases=restricting_aliases,
    )


@dataclass(frozen=True)
class ApprovalRequired:
    """What a held call answers: the link a person opens to approve it."""

    approval_id: str
    url: str
    message: str


def _refusal(text: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=f"Tool call refused: {text}")], is_error=True
    )


async def _record_tool_call(
    session: AsyncSession,
    scope: ClientScope,
    tool_name: str,
    arguments: dict,
    decision: ToolAuthorizationDecision,
    *,
    resource_type: str,
    resource_id: str,
    approval_id: str | None = None,
) -> None:
    from agentarea_common.audit import AuditService

    owner = None if tool_name in scope.platform_tools else scope.proxy.owner_of(tool_name)
    metadata: dict = {
        "tool": tool_name,
        "decision": decision.action.value,
        "reason": decision.reason,
        "argument_keys": sorted(arguments),
    }
    if owner is not None:
        metadata["mcp_instance_id"] = str(owner[0].mcp_instance_id)
    if approval_id is not None:
        metadata["approval_id"] = approval_id
    await AuditService(session, scope.user_context).record(
        "tool.call.allowed" if decision.allowed else "tool.call.denied",
        resource_type,
        resource_id,
        actor_type=scope.actor_type,
        event_metadata=metadata,
    )


async def _audit_tool_call(
    scope: ClientScope,
    tool_name: str,
    arguments: dict,
    decision: ToolAuthorizationDecision,
    *,
    resource_type: str,
    resource_id: str,
) -> None:
    """Record one tool call's verdict, against what it was made through, before anything runs.

    Written in its own transaction ahead of the call, so a call that runs is
    always on record, and a failure to record stops the call. Argument values
    never reach the trail — only their keys.
    """
    from agentarea_common.config.database import get_database

    async with get_database().session() as session:
        await _record_tool_call(
            session,
            scope,
            tool_name,
            arguments,
            decision,
            resource_type=resource_type,
            resource_id=resource_id,
        )


def _held_call(
    scope: ClientScope,
    tool_name: str,
    arguments: dict,
    decision: ToolAuthorizationDecision,
) -> ToolCallRequest:
    """The exact call a person is asked to approve, with the approvers the policy names."""
    owner = None if tool_name in scope.platform_tools else scope.proxy.owner_of(tool_name)
    if owner is None:
        instance_id, connector, raw_name = None, "AgentArea", tool_name
    else:
        member, raw_name = owner
        instance_id = str(member.mcp_instance_id)
        connector = scope.proxy.instance_names.get(instance_id) or instance_id
    return ToolCallRequest(
        mcp_instance_id=instance_id,
        connector=connector,
        tool=raw_name,
        policy_name=tool_name,
        arguments=arguments,
        reason=decision.reason,
        approvers=approvers_for_tool(
            scope.tool_policy, tool_name, aliases=_policy_aliases(scope, tool_name)
        ),
        client_id=scope.client_id,
        client_name=scope.client_name,
    )


async def _gate_held_call(
    scope: ClientScope,
    tool_name: str,
    arguments: dict,
    decision: ToolAuthorizationDecision,
    *,
    resource_type: str,
    resource_id: str,
) -> CallToolResult | ApprovalRequired | None:
    """Pass a held call through its approval: ``None`` when an approval lets it run.

    The approval is consumed and the verdict audited in one transaction, before
    the call runs, so an approval is spent only by a call that is on record.
    """
    from agentarea_common.base.repository_factory import RepositoryFactory
    from agentarea_common.base.tenant_scope import workspace_scope
    from agentarea_common.config.database import get_database
    from agentarea_common.workspaces.lookup import workspace_slug_for
    from agentarea_governance.application.tool_call_approvals import ToolCallApprovalService

    from .tool_call_approvals import approval_page_url

    user_ctx = scope.user_context
    request = _held_call(scope, tool_name, arguments, decision)
    with workspace_scope(user_ctx.workspace_id):
        async with get_database().session() as session:
            outcome = await ToolCallApprovalService(RepositoryFactory(session, user_ctx)).gate(
                request
            )
            approval = outcome.approval
            if outcome.verdict is GateVerdict.RUN:
                decision = ToolAuthorizationDecision(
                    ToolAuthorizationAction.ALLOW,
                    f"approved by {approval.decided_by} (approval {approval.id})",
                )
            elif outcome.verdict is GateVerdict.REJECTED:
                decision = ToolAuthorizationDecision(
                    ToolAuthorizationAction.DENY,
                    f"rejected by {approval.decided_by} (approval {approval.id})",
                )
            await _record_tool_call(
                session,
                scope,
                tool_name,
                arguments,
                decision,
                resource_type=resource_type,
                resource_id=resource_id,
                approval_id=approval.id,
            )
    if outcome.verdict is GateVerdict.RUN:
        return None
    if outcome.verdict is GateVerdict.REJECTED:
        comment = f" ({approval.comment})" if approval.comment else ""
        return _refusal(f"the user rejected this call{comment}. Change the arguments to ask again.")
    slug = user_ctx.workspace_slug or await workspace_slug_for(user_ctx.workspace_id)
    url = approval_page_url(slug, approval.id)
    return ApprovalRequired(
        approval_id=approval.id,
        url=url,
        message=(
            f"The workspace policy requires approval to run {approval.tool} on "
            f"{approval.connector}. Ask the user to open the link and approve; then call "
            f"again with the same arguments: {url}"
        ),
    )


async def _record_platform_tool_call(user_ctx: UserContext, usage: PlatformToolUsage) -> None:
    """Write a platform-funded call's line to the spend ledger, as a run's activity does."""
    from agentarea_common.base.tenant_scope import workspace_scope
    from agentarea_common.config.database import get_database
    from agentarea_tasks.domain.costs import platform_tool_call_entry
    from agentarea_tasks.infrastructure.cost_repository import CostEntryRepository

    with workspace_scope(user_ctx.workspace_id):
        async with get_database().session() as session:
            await CostEntryRepository(session, user_ctx).record([platform_tool_call_entry(usage)])


def _platform_funded(scope: ClientScope, tool_name: str) -> str | None:
    """What a call of ``tool_name`` buys on a platform-managed connection; see metering."""
    owner = None if tool_name in scope.platform_tools else scope.proxy.owner_of(tool_name)
    if owner is None:
        return None
    member, raw_name = owner
    instance = (scope.instances or {}).get(str(member.mcp_instance_id))
    return platform_funded_resource(instance, raw_name)


async def _governed_call(
    scope: ClientScope,
    tool_name: str,
    arguments: dict,
    invoke: Callable[[], Awaitable[CallToolResult]],
    *,
    resource_type: str,
    resource_id: str,
    restricting_aliases: Sequence[str] = (),
) -> CallToolResult | ApprovalRequired:
    """Run one call through the tool-call layer, as a run's tool activity does.

    The layer judges it (PDP), prices and gates a call on a platform-managed
    connection on the workspace's balance, runs it and writes its spend ledger line,
    with this client and no task. A held call is passed to its approval here and,
    once approved, through the layer again.
    """
    resource_ref = _platform_funded(scope, tool_name)
    user_ctx = scope.user_context
    call = GovernedToolCall(
        authorization=ToolAuthorizationRequest(
            tool_name=tool_name,
            tool_args=arguments,
            user_id=user_ctx.user_id,
            workspace_id=user_ctx.workspace_id,
            effective_policy=scope.tool_policy,
            aliases=_policy_aliases(scope, tool_name),
            restricting_aliases=restricting_aliases,
        ),
        call_id=str(uuid4()),
        agent_id=None,
        task_id=None,
        client_id=scope.client_id,
        platform_funded=PlatformFundedTool(resource_ref) if resource_ref is not None else None,
    )

    async def audit(decision: ToolAuthorizationDecision) -> None:
        await _audit_tool_call(
            scope,
            tool_name,
            arguments,
            decision,
            resource_type=resource_type,
            resource_id=resource_id,
        )

    async def ledger(usage: PlatformToolUsage) -> None:
        await _record_platform_tool_call(user_ctx, usage)

    async def audit_refusal(decision: ToolAuthorizationDecision) -> None:
        if not decision.allowed:
            await audit(decision)

    async def run() -> ToolCallOutcome:
        result = await invoke()
        quantity = (
            reported_quantity(result.meta, call.platform_funded.resource_ref)
            if call.platform_funded
            else None
        )
        return ToolCallOutcome(success=not result.is_error, usage_quantity=quantity, value=result)

    layered = await run_tool_call(call, run, audit=audit, ledger=ledger)
    if layered.verdict is Verdict.HELD:
        held = await _gate_held_call(
            scope,
            tool_name,
            arguments,
            layered.decision,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if held is not None:
            return held
        # The approval is already on record; only a later refusal is new.
        layered = await run_tool_call(
            replace(call, approval_granted=True),
            run,
            audit=audit_refusal,
            ledger=ledger,
        )
    if layered.verdict is not Verdict.RAN or layered.outcome is None:
        return _refusal(layered.decision.reason)
    return layered.outcome.value


async def call_instance_tool(
    session: AsyncSession,
    user_ctx: UserContext,
    instance_service: MCPServerInstanceService,
    instance: Any,
    tool_name: str,
    arguments: dict,
) -> CallToolResult | ApprovalRequired:
    """Run one of *instance*'s tools as the caller, the way a client's endpoint runs it.

    The same resolved url and credentials, the same policy verdict and the same
    audit record, filed against the connection instead of a client. A call the
    policy holds for approval answers with its approval link.
    """
    proxy = await _aggregate_instances(instance.name, "", instance_service, [instance], {})
    if not proxy.members:
        return CallToolResult(
            content=[TextContent(type="text", text=f"{instance.name} is unreachable: no address")],
            is_error=True,
        )
    scope = ClientScope(
        proxy=proxy,
        skill_registry={},
        platform_tools=frozenset(),
        user_context=user_ctx,
        tool_policy=await _effective_tool_policy(session, user_ctx),
        actor_type="client" if user_ctx.client_id else "user",
        client_id=user_ctx.client_id,
    )
    name = proxy.qualified_name(proxy.members[0], tool_name)
    return await _governed_call(
        replace(scope, instances={str(instance.id): instance}),
        name,
        arguments,
        lambda: proxy.call_namespaced_tool_result(name, arguments),
        resource_type="mcp_instance",
        resource_id=str(instance.id),
    )


async def call_openapi_tool(
    session: AsyncSession,
    user_ctx: UserContext,
    connection_service: OpenAPIConnectionService,
    connection: Any,
    tool_name: str,
    arguments: dict,
) -> CallToolResult | ApprovalRequired:
    """Run one operation of an OpenAPI *connection* as the caller, the way an agent runs it.

    The request is the agent's ``OpenAPITool``; the policy verdict and the audit
    record are a connector tool's, filed against the connection. A rule naming
    the operation, the connection or its id governs the call, as it governs an
    agent's. A call the policy holds for approval answers with its approval link.
    """
    from agentarea_agents_sdk.tools.openapi_tool import OpenAPIToolFactory

    tools = await OpenAPIToolFactory.create_tools_from_connection(
        connection.id, [tool_name], connection_service
    )
    if not tools:
        return CallToolResult(
            content=[
                TextContent(type="text", text=f"{connection.name} has no operation {tool_name}")
            ],
            is_error=True,
        )
    tool = tools[0]

    async def invoke() -> CallToolResult:
        result = await tool.execute(**arguments)
        text = result["result"] if result["success"] else result["error"]
        return CallToolResult(
            content=[TextContent(type="text", text=text or "")], is_error=not result["success"]
        )

    scope = ClientScope(
        proxy=MCPAggregatorProxy(connection.name, "", [], {}, {}),
        skill_registry={},
        platform_tools=frozenset(),
        user_context=user_ctx,
        tool_policy=await _effective_tool_policy(session, user_ctx),
        actor_type="client" if user_ctx.client_id else "user",
        client_id=user_ctx.client_id,
    )
    return await _governed_call(
        scope,
        tool.name,
        arguments,
        invoke,
        resource_type="openapi_connection",
        resource_id=str(connection.id),
        restricting_aliases=(tool_name, connection.name, str(connection.id)),
    )


def _activate_skill_tool(skill_registry: dict) -> Tool:
    return Tool(
        name="activate_skill",
        description="Load full instructions for an available skill by name.",
        input_schema={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "enum": list(skill_registry.keys()),
                    "description": "Name of the skill to activate.",
                }
            },
            "required": ["skill_name"],
        },
    )


async def _list_tools(_ctx: object, _params: PaginatedRequestParams | None) -> ListToolsResult:
    client_id = _client_id_var.get()
    if not client_id:
        return ListToolsResult(tools=[])
    try:
        scope = await _resolve_client_scope(client_id)
    except ClientAccessDeniedError:
        raise ValueError("Not authorized for this client") from None
    if scope is None:
        return ListToolsResult(tools=[])
    tools: list[Tool] = []
    if scope.platform_tools:
        with selected_tools(scope.platform_tools):
            tools.extend(await client_platform_server().list_tools())
    tools.extend(
        Tool(
            name=t["name"],
            description=t["description"],
            input_schema=t.get("input_schema") or t["inputSchema"],
        )
        for t in await scope.proxy.list_namespaced_tools()
    )
    # Disclosed is a subset of authorized: a tool the client may never run is not
    # offered. One held for approval is: an approval link lets it run.
    tools = [
        tool
        for tool in tools
        if _client_tool_decision(scope, tool.name).action is not ToolAuthorizationAction.DENY
    ]
    if scope.skill_registry:
        tools.append(_activate_skill_tool(scope.skill_registry))
    return ListToolsResult(tools=tools)


async def _call_tool(_ctx: object, params: CallToolRequestParams) -> CallToolResult:
    client_id = _client_id_var.get()
    if not client_id:
        raise ValueError("No client scope on request")
    try:
        scope = await _resolve_client_scope(client_id)
    except ClientAccessDeniedError:
        raise ValueError("Not authorized for this client") from None
    if scope is None:
        raise ValueError("Client not found")

    arguments = params.arguments or {}
    if params.name == "activate_skill":
        # Control flow over the client's own skills, not a capability: policy
        # never gates it, as for an agent (CONTROL_FLOW_TOOL_NAMES).
        from agentarea_agents_sdk.skills.skill_toolset import SkillActivationTool

        skill_name = arguments.get("skill_name", "")
        result = SkillActivationTool(scope.skill_registry).activate_skill(skill_name)
        text = result if isinstance(result, str) else str(result)
        return CallToolResult(content=[TextContent(type="text", text=text)])

    is_platform_tool = params.name in scope.platform_tools
    if not is_platform_tool and scope.proxy.owner_of(params.name) is None:
        # Not a tool of this client: nothing to judge, nothing ran.
        raise ValueError(f"No member owns tool {params.name}")

    async def invoke() -> CallToolResult:
        if is_platform_tool:
            # Run as the caller in the client's workspace: the tool's own
            # authorization checks apply exactly as on /mcp/w/{workspace}.
            with use_mcp_user_context(scope.user_context), selected_tools(scope.platform_tools):
                return await client_platform_server().call_tool_result(params.name, arguments)
        return await scope.proxy.call_namespaced_tool_result(params.name, arguments)

    result = await _governed_call(
        scope,
        params.name,
        arguments,
        invoke,
        resource_type="client",
        resource_id=client_id,
    )
    if isinstance(result, ApprovalRequired):
        return CallToolResult(
            content=[TextContent(type="text", text=result.message)], is_error=True
        )
    return result


# The tool set is resolved per request from the client scope, so this is the
# low-level Server with its list/call handlers, not a decorator-built MCPServer.
client_mcp_server = Server(
    "AgentArea Client",
    instructions="Scoped tool bundle for a registered client (agent-proxy).",
    on_list_tools=_list_tools,
    on_call_tool=_call_tool,
)


class ClientMCPScopeMiddleware:
    """Extracts the client id from ``{prefix}/{client_id}`` and rewrites the
    path to the mount root so the inner MCP app serves it.
    """

    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self._prefix = prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        if path.startswith(f"{self._prefix}/"):
            path = path[len(self._prefix) :]
        client_id: str | None = None
        if path.startswith("/"):
            client_id, _, tail = path[1:].partition("/")
            client_id = client_id or None
            scope = dict(scope)
            scope["path"] = f"/{tail}" if tail else "/"
            if client_id:
                # Name the resource for the auth middleware's 401: each client's
                # endpoint is its own RFC 9728 resource, and a harness rejects
                # metadata whose `resource` does not match the URL it called.
                scope[PROTECTED_RESOURCE_SCOPE_KEY] = f"{self._prefix.strip('/')}/{client_id}"
        token = _client_id_var.set(client_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _client_id_var.reset(token)
