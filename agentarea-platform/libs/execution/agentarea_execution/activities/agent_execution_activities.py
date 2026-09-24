"""Agent execution activities for Temporal workflows.

This module provides Temporal activities for agent execution:

1. **State Management**: Uses TypedDict state passed between workflow activities
2. **Flow Control**: Workflow orchestrates activities step-by-step with conditional logic
3. **Tool Integration**: Direct MCP tool calls via execute_mcp_tool_activity
4. **Message Format**: OpenAI-compatible message format for LLM interactions
5. **Execution Model**: Activity-based with explicit Temporal workflow orchestration
6. **LLM Integration**: Uses real LLM services for model resolution and execution
"""

# Standard library imports
import asyncio
import hashlib
import itertools
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from agentarea_agents.domain.config_hash import compute_agent_config_hash
from agentarea_agents_sdk import (
    GoalProgressEvaluator,
    LLMModel,
    LLMRequest,
    ToolExecutor,
    ToolManager,
)
from agentarea_agents_sdk.tools.invocation_context import ToolInvocationContext
from agentarea_agents_sdk.tools.tool_builders import allowed_tool_names

# Local imports
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    ToolAuthorizationRequest,
    authorize_tool_invocation,
)
from agentarea_common.events.contract import LLM_FAILED, canonical_type
from agentarea_common.money import ZERO, to_money
from agentarea_wallet.domain.enums import settlement_status
from prometheus_client import Counter

# Third-party imports
from temporalio import activity
from temporalio.exceptions import ApplicationError

from .. import llm_execution_service
from ..exceptions import AgentNotFoundError, ModelInstanceNotFoundError, NoModelBoundError
from ..interfaces import ActivityDependencies

# Add import for new Pydantic models
from ..models import (
    AgentConfigRequest,
    AgentConfigResult,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    CompactMessagesRequest,
    CompactMessagesResult,
    CreateDelegationTaskRequest,
    CreateDelegationTaskResult,
    DiscoverToolProvidersResult,
    ExecutionPlanRequest,
    ExecutionPlanResult,
    GoalEvaluationRequest,
    GoalEvaluationResult,
    LLMCallRequest,
    LLMCallResult,
    LLMUsage,
    MaterializeSkillFilesRequest,
    MaterializeSkillFilesResult,
    MCPToolRequest,
    MCPToolResult,
    McpToolRoute,
    MonthlySpendCapRequest,
    MonthlySpendCapResult,
    ReadOutputRequest,
    ReadOutputResult,
    RecallHistoryRequest,
    RecallHistoryResult,
    ResolveAgentToolsRequest,
    ResolveAgentToolsResult,
    ResolvedModelInfo,
    ResolveModelRequest,
    RuntimeDiscoveryResult,
    SearchableToolEntry,
    SearchHistoryRequest,
    SearchHistoryResult,
    SkillInfo,
    StoreHistoryRequest,
    StoreHistoryResult,
    StoreOutputRequest,
    StoreOutputResult,
    ToolDefinition,
    ToolDiscoveryRequest,
    ToolDiscoveryResult,
    ToolProviderData,
    UpdateTaskGovernanceSnapshotRequest,
    UpdateTaskGovernanceSnapshotResult,
    UpdateTaskStatusRequest,
    UpdateTaskStatusResult,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from .artifact_validation import validate_published_artifacts
from .event_publisher import create_event_publisher, publish_enriched_llm_error_event
from .heartbeat import auto_heartbeater
from .runtime_discovery import fetch_runtime_manifest, render_runtime_prompt, runtime_event_data

logger = logging.getLogger(__name__)


def _make_counter(name: str, doc: str, labels: list[str] | None = None):
    return Counter(name, doc, labels or [])


def _as_tool_config_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _task_resource_ids(parameters: dict[str, Any], kind: str) -> list[UUID]:
    value = parameters.get(kind)
    if kind == "mcps" and value is None:
        value = parameters.get("mcp")
        if value is None:
            value = parameters.get("mcp_servers")
    if value is None:
        return []
    if not isinstance(value, list):
        raise ApplicationError(f"Task {kind} must be a list", non_retryable=True)
    ids: list[UUID] = []
    for item in value:
        ref = item
        if isinstance(item, dict):
            ref = item.get("id") or item.get("instance_id") or item.get("skill_id")
        try:
            resource_id = UUID(ref) if isinstance(ref, str) else None
        except ValueError:
            resource_id = None
        if resource_id is None:
            raise ApplicationError(f"Invalid task {kind} reference", non_retryable=True)
        if resource_id not in ids:
            ids.append(resource_id)
    return ids


async def _resolve_task_resources(
    agent: Any, parameters: dict[str, Any], ctx: Any
) -> tuple[list[dict[str, Any]], list[Any]]:
    """Resolve additive run resources with the task's workspace-scoped services."""
    tools = deepcopy(_as_tool_config_list(agent.tools))
    skills = list(getattr(agent, "skills", None) or [])
    mcp_ids = _task_resource_ids(parameters, "mcps")
    if mcp_ids:
        mcp_service = await ctx.get_mcp_server_instance_service()
        for instance_id in mcp_ids:
            instance = await mcp_service.get(instance_id)
            if instance is None:
                raise ApplicationError("Selected task MCP is unavailable", non_retryable=True)
            # Match both storage conventions. An inherited restriction must never
            # be replaced by a second, unrestricted entry for the same server.
            inherited = False
            for tool in tools:
                if tool.get("type") != "mcp":
                    continue
                reference = str(tool.get("name") or "")
                if reference == instance.name:
                    inherited = True
                    break
                try:
                    inherited = UUID(reference) == instance.id
                except ValueError:
                    pass
                if inherited:
                    break
            if not inherited:
                tools.append({"type": "mcp", "name": str(instance.id)})

    skill_ids = _task_resource_ids(parameters, "skills")
    if skill_ids:
        skill_service = await ctx.get_skill_service()
        for skill_id in skill_ids:
            if any(str(skill.id) == str(skill_id) for skill in skills):
                continue
            skill = await skill_service.get_with_catalog(skill_id)
            if skill is None:
                raise ApplicationError("Selected task skill is unavailable", non_retryable=True)
            if any(existing.name == skill.name for existing in skills):
                raise ApplicationError(
                    "Selected task skills must have distinct names", non_retryable=True
                )
            skills.append(skill)
    return tools, skills


async def _prepare_task_files(
    request: AgentConfigRequest, user_context: UserContext
) -> list[dict[str, Any]]:
    """Snapshot explicitly selected workspace files into this run's inputs."""
    from agentarea_common.artifacts import (
        ArtifactActor,
        ArtifactService,
        DbArtifactEventRecorder,
        WorkspaceRepository,
        WorkspaceValidationError,
    )
    from agentarea_common.artifacts.workspace import normalize_workspace_path

    paths = request.task_parameters.get("files")
    if paths is None or paths == []:
        return []
    if not isinstance(paths, list) or len(paths) > 100 or request.task_id is None:
        raise ApplicationError("Invalid task file selection", non_retryable=True)

    sources: list[tuple[str, str | None, str]] = []
    for path in paths:
        try:
            clean = normalize_workspace_path(path)
            parts = PurePosixPath(clean).parts
            if not parts:
                raise ValueError("not a file path")
            source_task_id = None
            relative_path = clean
            if parts[0] == "tasks":
                if len(parts) < 4 or parts[2] != "workspace":
                    raise ValueError("not a public task workspace path")
                source_task_id = str(UUID(parts[1]))
                relative_path = normalize_workspace_path("/".join(parts[3:]))
            elif parts[0] in {"staging", ".trash"} or "://" in clean:
                raise ValueError("not a visible workspace file")
        except (ValueError, TypeError, WorkspaceValidationError) as exc:
            raise ApplicationError("Invalid task file path", non_retryable=True) from exc
        source = (clean, source_task_id, relative_path)
        if source not in sources:
            sources.append(source)

    workspace_id = user_context.workspace_id
    task_id = str(request.task_id)
    repository = WorkspaceRepository(
        recorder=DbArtifactEventRecorder(),
        actor=ArtifactActor(user_id=user_context.user_id),
    )
    artifacts = ArtifactService()
    descriptors: list[dict[str, Any]] = []
    for source, source_task_id, source_path in sources:
        # A stable name makes activity retries reuse the first committed snapshot
        # even if the source has since changed or disappeared.
        basename = PurePosixPath(source_path).name
        prefix = hashlib.sha256(source.encode()).hexdigest()[:16]
        filename = f"selected-{prefix}-{basename}"
        target = f"inputs/attachments/{filename}"
        try:
            data, content_type = await repository.get(workspace_id, task_id, target)
        except FileNotFoundError:
            try:
                if source_task_id is not None:
                    data, content_type = await repository.get(
                        workspace_id, source_task_id, source_path
                    )
                else:
                    head = await artifacts.head(workspace_id, source_path)
                    if head is None or not head.get("sha256"):
                        raise FileNotFoundError(source_path)
                    data, content_type = await artifacts.get(workspace_id, source_path)
                    if (
                        len(data) != head["size"]
                        or hashlib.sha256(data).hexdigest() != head["sha256"]
                    ):
                        raise WorkspaceValidationError("selected file changed during snapshot")
                await repository.put_files(
                    workspace_id,
                    task_id,
                    {target: data},
                    content_types={target: content_type or "application/octet-stream"},
                    provenance={"source": "task_selection", "source_path": source},
                    owner=f"task-inputs-{task_id}",
                )
            except (FileNotFoundError, WorkspaceValidationError) as exc:
                raise ApplicationError(
                    "Selected task file is unavailable", non_retryable=True
                ) from exc
        descriptors.append(
            {
                "relative_path": target,
                "filename": filename,
                "size": len(data),
                "content_type": content_type or "application/octet-stream",
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return descriptors


def _sandbox_file_auth_secret(dependencies: ActivityDependencies) -> str:
    secret = dependencies.settings.mcp.SANDBOX_FILE_AUTH_SECRET
    if secret is None or not secret.get_secret_value():
        raise ValueError("SANDBOX_FILE_AUTH_SECRET is required for sandbox file access")
    return secret.get_secret_value()


async def _record_task_config_hash(ctx: Any, task_id: UUID, config_hash: str) -> None:
    """Stamp the run with the hash of the agent config it resolved.

    Recorded so a finished run can be told apart from the agent's current
    definition. Best-effort: losing the stamp must not fail the run, but it is
    logged loudly enough to notice.
    """
    from agentarea_tasks.infrastructure.repository import TaskRepository

    try:
        session = ctx.container._database.async_session_factory()
        ctx._sessions.append(session)
        repo = TaskRepository(session, ctx.user_context)
        # ActivityContext commits every session it owns on exit.
        if not await repo.merge_metadata(task_id, {"agent_config_hash": config_hash}):
            logger.warning("Task %s vanished before its config hash could be recorded", task_id)
    except Exception:
        logger.warning("Failed to record config hash for task %s", task_id, exc_info=True)


def _sandbox_control_auth_secret(dependencies: ActivityDependencies) -> str:
    secret = dependencies.settings.mcp.SANDBOX_CONTROL_AUTH_SECRET
    if secret is None:
        raise ValueError("SANDBOX_CONTROL_AUTH_SECRET is required for sandbox execution")
    value = secret.get_secret_value()
    if len(value.encode()) < 32:
        raise ValueError("SANDBOX_CONTROL_AUTH_SECRET must contain at least 32 bytes")
    return value


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


# Prometheus counters for MCP dispatch telemetry
_mcp_last_dispatch_dropped_total = _make_counter(
    "mcp_last_dispatch_dropped_total",
    "Number of last_dispatch writes dropped due to full queue",
)
_mcp_dispatch_failed_total = _make_counter(
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
        logger.warning("Activity output offload failed for %s: %s", output_id, exc)
        head = content[:TOOL_OUTPUT_OFFLOAD_CHARS]
        return (
            f"{head}\n... [activity output truncated at {TOOL_OUTPUT_OFFLOAD_CHARS} chars; "
            f"offload failed: {exc}]"
        )


def _agent_artifact_actor(request, user_context):
    """Build the provenance actor for files an agent writes during a task."""
    from agentarea_common.artifacts import ACTOR_AGENT, ArtifactActor

    agent_id = getattr(request, "agent_id", None)
    task_id = getattr(request, "task_id", None)
    return ArtifactActor(
        user_id=str(user_context.user_id),
        actor_type=ACTOR_AGENT,
        agent_id=str(agent_id) if agent_id else None,
        task_id=str(task_id) if task_id else None,
    )


# Bounded queue for fire-and-forget last_dispatch persistence (instance_id, payload)
_last_dispatch_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)


async def _flush_last_dispatch_loop(get_session) -> None:
    """Batch-flush last_dispatch updates every 500ms or 100 entries, whichever first."""
    from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
    from sqlalchemy import update

    while True:
        await asyncio.sleep(0.5)
        batch: list[tuple[str, dict]] = []
        try:
            while len(batch) < 100:
                batch.append(_last_dispatch_queue.get_nowait())
        except asyncio.QueueEmpty:
            pass
        if not batch:
            continue
        try:
            async with get_session() as session:
                for instance_id, payload in batch:
                    await session.execute(
                        update(MCPServerInstance)
                        .where(MCPServerInstance.id == instance_id)
                        .values(last_dispatch=payload)
                    )
                await session.commit()
        except Exception:
            logger.error("last_dispatch flush failed", exc_info=True)


def _enqueue_last_dispatch(instance_id: str, payload: dict) -> None:
    """Push a last_dispatch update onto the bounded queue. Never blocks."""
    try:
        _last_dispatch_queue.put_nowait((instance_id, payload))
    except asyncio.QueueFull:
        _mcp_last_dispatch_dropped_total.inc()


def make_agent_activities(dependencies: ActivityDependencies):
    """Factory function to create agent activities with injected dependencies.

    Args:
        dependencies: Basic dependencies needed to create services

    Returns:
        List of activity functions ready for worker registration
    """
    from .dependencies import (
        ActivityContext,
        ActivityServiceContainer,
        create_user_context,
    )

    # Create service container
    container = ActivityServiceContainer(dependencies)

    @asynccontextmanager
    async def model_service_scope(user_context: UserContext):
        async with ActivityContext(container, user_context) as ctx:
            yield await ctx.get_model_instance_service()

    llm_service = llm_execution_service.LLMExecutionService(
        model_service_scope=model_service_scope,
        secret_manager_factory=dependencies.secret_manager_factory,
        local_host=dependencies.settings.app.local_host,
    )

    @activity.defn
    async def discover_runtime_manifest_activity() -> RuntimeDiscoveryResult:
        """Discover the manifest exposed by the active sandbox data plane."""
        return await fetch_runtime_manifest(dependencies.settings.mcp.MCP_MANAGER_URL)

    @activity.defn(name="validate_artifacts_activity")
    async def validate_artifacts_activity(
        request: ArtifactValidationRequest,
    ) -> ArtifactValidationResult:
        """Completion barrier: persist the declared files before the task is done."""
        if not request.declared_paths:
            return ArtifactValidationResult(state="passed", generation=0)
        return await validate_published_artifacts(
            request,
            manager_url=dependencies.settings.mcp.MCP_MANAGER_URL,
            auth_secret=_sandbox_file_auth_secret(dependencies),
        )

    @activity.defn
    async def build_agent_config_activity(
        request: AgentConfigRequest,
    ) -> AgentConfigResult:
        """Build agent configuration including skills."""
        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            agent_service = await ctx.get_agent_service()

            # Get agent from database with skills. Built-in agents live in the
            # registry catalog (ADR-003) and are run directly from their
            # definition (run-from-definition) without materializing a tenant
            # row, so fall back to the catalog projection when there is no
            # tenant agent for this id.
            agent = await agent_service.get_with_skills(request.agent_id)
            if not agent:
                agent = await agent_service.get_with_catalog(request.agent_id)
            if not agent:
                raise AgentNotFoundError(f"Agent {request.agent_id} not found")

            tools, skills = await _resolve_task_resources(agent, request.task_parameters, ctx)
            runtime = await discover_runtime_manifest_activity()

            # Build skill information
            skills_info = []
            if skills:
                for skill in skills:
                    # Get file list for multi-file skills
                    files = []
                    if skill.s3_path:
                        # For multi-file skills, we would list files from S3
                        # For now, just note it has additional files
                        files = ["(additional files available)"]

                    skills_info.append(
                        SkillInfo(
                            id=str(skill.id),
                            name=skill.name,
                            description=skill.description or "",
                            content=skill.content or "",
                            files=files,
                        )
                    )

            # Fetch model context window and context strategy from ModelSpec
            model_id_str = request.override_model or agent.model_id
            if not model_id_str:
                # An agent forked from the catalog starts with no model bound.
                # Fail here with the reason rather than letting UUID("") blow up
                # inside call_llm three layers down.
                raise NoModelBoundError(
                    f"Agent {agent.id} has no model bound. Assign a model instance to the "
                    "agent, or pass override_model when starting the task."
                )
            model_instance_service = await ctx.get_model_instance_service()
            model_instance = await model_instance_service.get(UUID(model_id_str))
            if not model_instance or not model_instance.model_spec:
                raise ModelInstanceNotFoundError(
                    f"Model instance {model_id_str} or its ModelSpec was not found"
                )
            context_window = model_instance.model_spec.context_window
            if (
                isinstance(context_window, bool)
                or not isinstance(context_window, int)
                or context_window <= 0
            ):
                raise ValueError(f"ModelSpec for {model_id_str} has no valid context_window")
            default_context_strategy = getattr(
                model_instance.model_spec, "default_context_strategy", None
            )

            config_hash = compute_agent_config_hash(
                {
                    "instruction": agent.instruction,
                    "model_id": model_id_str,
                    "tools": tools,
                    "events_config": agent.events_config,
                    "planning": agent.planning,
                    "agent_type": getattr(agent, "agent_type", None),
                },
                skill_ids=[str(s.id) for s in skills],
            )
            if request.task_id is not None:
                await _record_task_config_hash(ctx, request.task_id, config_hash)

            execution_context = deepcopy(request.execution_context)
            attachments = await _prepare_task_files(request, user_context)
            if attachments:
                execution_context = execution_context or {}
                execution_context["workspace_attachments"] = [
                    *(execution_context.get("workspace_attachments") or []),
                    *attachments,
                ]

            # Build configuration using Pydantic model
            return AgentConfigResult(
                id=str(agent.id),
                name=agent.name,
                description=agent.description or "",
                instruction=(agent.instruction or "")
                + render_runtime_prompt(
                    runtime,
                    has_org_context=any(t.get("name") == "agentarea/context" for t in tools),
                ),
                agent_type=getattr(agent, "agent_type", "stateless") or "stateless",
                model_id=model_id_str,
                config_hash=config_hash,
                context_window=context_window,
                default_context_strategy=default_context_strategy,
                tools=tools,
                events_config=agent.events_config or {},
                planning=agent.planning if agent.planning is not None else False,
                a2ui_enabled=agent.a2ui_enabled if agent.a2ui_enabled is not None else False,
                execution_context=execution_context,
                step_type=request.step_type,
                skills=skills_info,
                runtime=runtime,
                runtime_event_data=runtime_event_data(runtime),
            )

    @activity.defn
    async def discover_available_tools_activity(
        request: ToolDiscoveryRequest,
    ) -> ToolDiscoveryResult:
        """Discover available tools for an agent.

        Honors `settings.load_mode` per OpenAPI tool — operations marked
        `searchable` go into `searchable_entries` (deferred pool) instead of
        `tools` (the per-call LLM context).
        """
        user_context = create_user_context(request.user_context_data)

        async with ActivityContext(container, user_context) as ctx:
            agent_service = await ctx.get_agent_service()
            mcp_server_instance_service = await ctx.get_mcp_server_instance_service()
            openapi_connection_service = await ctx.get_openapi_connection_service()

            # Get agent configuration
            agent = await agent_service.get(request.agent_id)
            if not agent:
                raise AgentNotFoundError(f"Agent {request.agent_id} not found")

            # Use tool manager to discover available tools (split path).
            tool_manager = ToolManager(openapi_connection_service=openapi_connection_service)
            base_url = f"{dependencies.settings.app.API_BASE_URL}/api/v1"
            split = await tool_manager.discover_available_tools_split(
                agent_id=request.agent_id,
                tools_config=request.tools
                if request.tools is not None
                else _as_tool_config_list(agent.tools),
                mcp_server_instance_service=mcp_server_instance_service,
                agent_service=agent_service,
                base_url=base_url,
            )

            tool_defs = [ToolDefinition(**t) for t in split.explicit_tools]
            searchable = [
                SearchableToolEntry(
                    name=e.get("name", ""),
                    description=e.get("description", ""),
                    connection_id=e.get("connection_id", ""),
                    schema=e.get("schema") or {},
                    source_type=e.get("source_type", "openapi"),
                )
                for e in split.searchable_entries
            ]
            return ToolDiscoveryResult(
                tools=tool_defs,
                searchable_entries=searchable,
                mcp_tool_routes={
                    name: McpToolRoute.from_identity(identity)
                    for name, identity in split.tool_identities.items()
                },
            )

    @activity.defn
    async def discover_tool_providers_activity(
        request: ToolDiscoveryRequest,
    ) -> DiscoverToolProvidersResult:
        """Discover tool providers for progressive disclosure (DYNAMIC mode)."""
        user_context = create_user_context(request.user_context_data)

        async with ActivityContext(container, user_context) as ctx:
            agent_service = await ctx.get_agent_service()
            mcp_server_instance_service = await ctx.get_mcp_server_instance_service()
            openapi_connection_service = await ctx.get_openapi_connection_service()

            agent = await agent_service.get(request.agent_id)
            if not agent:
                return DiscoverToolProvidersResult(
                    success=False, error=f"Agent {request.agent_id} not found"
                )

            tool_manager = ToolManager(openapi_connection_service=openapi_connection_service)
            base_url = f"{dependencies.settings.app.API_BASE_URL}/api/v1"
            discovery = await tool_manager.discover_tool_providers(
                agent_id=request.agent_id,
                tools_config=request.tools
                if request.tools is not None
                else _as_tool_config_list(agent.tools),
                mcp_server_instance_service=mcp_server_instance_service,
                agent_service=agent_service,
                base_url=base_url,
            )

            # Serialize providers to transport models
            provider_data = []
            for p in discovery.providers:
                entry = p.get_catalog_entry()
                provider_data.append(
                    ToolProviderData(
                        name=p.name,
                        provider_type=p.provider_type,
                        tool_names=entry.tool_names,
                        description=entry.description,
                        tools=p.get_tool_definitions(),
                    )
                )

            return DiscoverToolProvidersResult(
                providers=provider_data,
                mcp_tool_routes={
                    name: McpToolRoute.from_identity(identity)
                    for name, identity in discovery.tool_identities.items()
                },
            )

    @activity.defn
    async def resolve_model_activity(
        request: ResolveModelRequest,
    ) -> dict:
        """Resolve model info once at workflow start and return as ResolvedModelInfo dict.

        This is called once during _initialize_agent_config and the result is cached
        in workflow state to avoid repeated DB lookups on every LLM call.
        """
        from datetime import UTC
        from uuid import UUID as _UUID

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            model_instance_service = await ctx.get_model_instance_service()
            model_instance = await model_instance_service.get(_UUID(request.model_id))
            if not model_instance:
                raise ModelInstanceNotFoundError(f"Model instance {request.model_id} not found")
            foreign = model_instance.foreign_part()
            if foreign is not None:
                raise ModelInstanceNotFoundError(
                    f"Model instance {request.model_id} uses a {foreign} from another workspace"
                )

            provider_type = model_instance.provider_config.provider_spec.provider_type
            model_name = model_instance.model_spec.model_name
            # endpoint_url lives on provider_config (ollama, self-hosted, etc.), not model_spec.
            endpoint_url = getattr(model_instance.provider_config, "endpoint_url", None) or getattr(
                model_instance.model_spec, "endpoint_url", None
            )
            context_window = model_instance.model_spec.context_window
            if (
                isinstance(context_window, bool)
                or not isinstance(context_window, int)
                or context_window <= 0
            ):
                raise ValueError(f"ModelSpec for {request.model_id} has no valid context_window")
            max_output_tokens = getattr(model_instance.model_spec, "max_output_tokens", None)
            input_cost_per_token = getattr(model_instance.model_spec, "input_cost_per_token", None)
            output_cost_per_token = getattr(
                model_instance.model_spec, "output_cost_per_token", None
            )
            api_key_secret = getattr(model_instance.provider_config, "api_key", None)
            managed_by = getattr(model_instance.provider_config, "managed_by", None)
            display_name = getattr(model_instance.model_spec, "display_name", None)
            provider_display_name = getattr(
                model_instance.provider_config.provider_spec, "display_name", None
            )

        resolved = ResolvedModelInfo(
            model_id=request.model_id,
            provider_type=provider_type,
            model_name=model_name,
            api_key_secret=api_key_secret,
            managed_by=managed_by,
            endpoint_url=endpoint_url,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            input_cost_per_token=input_cost_per_token,
            output_cost_per_token=output_cost_per_token,
            display_name=display_name,
            provider_display_name=provider_display_name,
            resolved_at=datetime.now(UTC).isoformat(),
        )
        return resolved.model_dump()

    @activity.defn
    @auto_heartbeater
    async def call_llm_activity(
        request: LLMCallRequest,
    ) -> LLMCallResult:
        """Adapt one model call to Temporal and the task event transport."""

        async def on_error(error: Exception, provider_type: str | None) -> None:
            if request.task_id and request.agent_id and dependencies.event_broker:
                await publish_enriched_llm_error_event(
                    error=error,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    execution_id=request.execution_id or "",
                    model_id=request.model_id,
                    provider_type=provider_type,
                    event_broker=dependencies.event_broker,
                )

        try:
            try:
                if not request.workspace_id and not request.user_context_data:
                    raise ValueError("Either workspace_id or user_context_data must be provided")
                user_context = create_user_context(request.user_context_data)
            except Exception as error:
                try:
                    await on_error(error, None)
                except Exception:
                    logger.exception("Failed to publish LLM context error")
                raise

            on_chunk = None
            if request.task_id:
                on_chunk = create_event_publisher(
                    dependencies.event_broker,
                    request.task_id,
                    execution_id=request.execution_id,
                    iteration=request.iteration,
                    broker_client=dependencies.broker_client,
                )

            return await llm_service.execute(
                request,
                user_context=user_context,
                on_chunk=on_chunk,
                on_error=on_error,
            )
        except Exception as error:
            from .event_publisher import _is_non_retryable_error

            error_message = str(error)
            logger.error(f"LLM call failed: {error_message}")
            raise ApplicationError(
                f"LLM call failed: {error_message}",
                type=type(error).__name__,
                non_retryable=_is_non_retryable_error(error),
            ) from error

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
                                auth_secret=_sandbox_file_auth_secret(dependencies),
                            ),
                            "workspace_id": str(request.workspace_id),
                        }
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
                                auth_secret=_sandbox_file_auth_secret(dependencies),
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
                            "auth_secret": _sandbox_control_auth_secret(dependencies),
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
                                actor=_agent_artifact_actor(request, user_context),
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
                from .payment_handler import payment_idempotency_key

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
                    "amount_usd": record.amount_usd,
                    "recipient": record.recipient,
                    "tx_hash": record.tx_hash,
                    "protocol_metadata": record.protocol_metadata or {},
                    "idempotency_key": idempotency_key,
                    "error": (
                        f"This request was already paid (tx {record.tx_hash}) by an earlier "
                        "attempt of the same tool call; not paying again"
                    ),
                }

            async def get_payment_context() -> tuple[Any, Any, dict[str, Any], str, float] | None:
                return None

            if request.agent_id:
                agent_id = request.agent_id

                async def get_payment_context() -> (
                    tuple[Any, Any, dict[str, Any], str, float] | None
                ):
                    try:
                        wallet_service = await ctx.get_wallet_service()
                        wallet = await wallet_service.get_wallet(agent_id)
                    except Exception as e:
                        logger.debug("No active wallet for payment handling: %s", e)
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
                    payment_context: tuple[Any, Any, dict[str, Any], str, float] | None,
                    result: dict[str, Any] | None,
                    *,
                    tool_name: str,
                    idempotency_key: str,
                ) -> None:
                    if not payment_context or not result or result.get("already_settled"):
                        return
                    if result.get("protocol") not in {"x402", "mpp"}:
                        return
                    amount = float(result.get("amount_usd") or 0.0)
                    if amount <= 0:
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

                    from .payment_handler import handle_402_payment

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

                    from agentarea_agents_sdk.tools.agent_tool_factory import (
                        AgentToolFactory,
                    )

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
                        from .mcp_payment_httpx import create_payment_httpx_client_factory

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
                        float(p.get("amount_usd") or 0.0) for p in mcp_payments if p.get("success")
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
                    service_cost=float(result.get("service_cost") or 0.0),
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

    @activity.defn
    async def create_execution_plan_activity(
        request: ExecutionPlanRequest,
    ) -> ExecutionPlanResult:
        """Create an execution plan based on the goal and available tools."""
        try:
            # For now, return a simple plan - could be enhanced with actual LLM call
            tool_names = [tool.get("name", "unknown") for tool in request.available_tools]

            return ExecutionPlanResult(
                plan=(
                    f"Execute the task '{request.goal.get('description', 'Unknown')}' "
                    "systematically using available tools"
                ),
                estimated_steps=min(max(len(request.available_tools), 3), 8),  # Between 3-8 steps
                key_tools=tool_names[:3],  # First 3 tools
                risk_factors=[
                    "Tool execution failures",
                    "LLM response issues",
                    "External API timeouts",
                ],
            )

        except Exception as e:
            logger.error(f"Failed to create execution plan: {e}")
            return ExecutionPlanResult(
                plan=(
                    f"Execute the task '{request.goal.get('description', 'Unknown')}' step by step"
                ),
                estimated_steps=5,
                key_tools=[],
                risk_factors=["Planning failed - proceeding with default approach"],
            )

    @activity.defn
    async def evaluate_goal_progress_activity(
        request: GoalEvaluationRequest,
    ) -> GoalEvaluationResult:
        """Evaluate progress toward the goal."""
        evaluator = GoalProgressEvaluator()

        # Extract goal information for the new interface
        goal_description = request.goal.get("description", "")
        success_criteria = request.goal.get("success_criteria", [])

        evaluation = await evaluator.evaluate_progress(
            goal_description=goal_description,
            success_criteria=success_criteria,
            conversation_history=request.messages,
            current_iteration=request.current_iteration,
        )

        return GoalEvaluationResult(
            goal_achieved=evaluation.get("goal_achieved", False),
            confidence=evaluation.get("confidence", 0.0),
            final_response=evaluation.get("final_response"),
            reasoning=evaluation.get("reasoning", ""),
            next_steps=evaluation.get("next_steps", []),
        )

    @activity.defn
    async def publish_workflow_events_activity(
        request: WorkflowEventsRequest,
    ) -> WorkflowEventsResult:
        """Publish workflow events."""
        try:
            import json
            from datetime import datetime
            from uuid import uuid4

            from agentarea_common.events.base_events import DomainEvent
            from agentarea_common.events.task_stream import publish_task_event

            from ..handlers import handle_llm_error_event
            from .event_publisher import resolve_event_broker

            logger.info(f"Publishing {len(request.events_json)} workflow events via EventBroker")

            event_publisher = resolve_event_broker(dependencies.event_broker)
            events_published = 0
            errors = []

            # Per-invocation cache of task_parameters → channel_origin, used
            # to avoid N+1 lookups when a single batch carries multiple
            # events for the same task.
            channel_origin_cache: dict[str, dict | None] = {}
            push_configs_cache: dict[str, list] = {}

            async def _resolve_push_configs(task_id_str: str) -> list:
                if task_id_str in push_configs_cache:
                    return push_configs_cache[task_id_str]
                configs: list = []
                try:
                    from uuid import UUID as _UUID

                    from agentarea_tasks.infrastructure.repository import (
                        TaskRepository as _TaskRepository,
                    )

                    user_context_inner = UserContext(
                        user_id=request.user_id,
                        workspace_id=request.workspace_id,
                    )
                    async with ActivityContext(container, user_context_inner) as ctx_inner:
                        session_inner = container._database.async_session_factory()
                        ctx_inner._sessions.append(session_inner)
                        task_repo = _TaskRepository(session_inner, user_context_inner)
                        task = await task_repo.get_task(_UUID(task_id_str))
                        if task and task.parameters:
                            raw = task.parameters.get("a2a_push_configs")
                            if isinstance(raw, list):
                                configs = raw
                except Exception:
                    logger.exception("a2a push-config lookup failed for task=%s", task_id_str)
                push_configs_cache[task_id_str] = configs
                return configs

            async def _resolve_channel_origin(task_id_str: str) -> dict | None:
                if task_id_str in channel_origin_cache:
                    return channel_origin_cache[task_id_str]
                origin: dict | None = None
                try:
                    from uuid import UUID as _UUID

                    from agentarea_tasks.infrastructure.repository import (
                        TaskRepository as _TaskRepository,
                    )

                    user_context_inner = UserContext(
                        user_id=request.user_id,
                        workspace_id=request.workspace_id,
                    )
                    async with ActivityContext(container, user_context_inner) as ctx_inner:
                        session_inner = container._database.async_session_factory()
                        ctx_inner._sessions.append(session_inner)
                        task_repo = _TaskRepository(session_inner, user_context_inner)
                        task = await task_repo.get_task(_UUID(task_id_str))
                        if task and task.parameters:
                            origin = task.parameters.get("channel_origin")
                except Exception:
                    logger.exception("channel_origin lookup failed for task=%s", task_id_str)
                channel_origin_cache[task_id_str] = origin
                return origin

            for event_json in request.events_json:
                try:
                    event = json.loads(event_json)
                    task_id = event.get("data", {}).get("task_id", "unknown")

                    # Create proper domain event with correct parameters
                    domain_event = DomainEvent(
                        event_id=event.get("event_id", str(uuid4())),
                        event_type=f"workflow.{event['event_type']}",  # Prefix for workflow events
                        timestamp=datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")),
                        # All other data goes into the data dict
                        aggregate_id=task_id,
                        aggregate_type="task",
                        original_event_type=event["event_type"],
                        original_timestamp=event["timestamp"],
                        original_data=event[
                            "data"
                        ],  # Include the original event data for tool calls
                    )

                    # 1. Publish via RedisEventBroker (uses FastStream
                    # infrastructure) for real-time SSE
                    await event_publisher.publish(domain_event)
                    logger.debug(
                        f"Published workflow event: {event['event_type']} for task {task_id}"
                    )

                    # 2. Store event in database using proper service layer
                    try:
                        # Use workspace_id and user_id from workflow request (already present)
                        workspace_id = request.workspace_id
                        user_id = request.user_id

                        # Create proper user context with values from workflow
                        user_context = UserContext(
                            user_id=user_id,
                            workspace_id=workspace_id,
                        )

                        persisted_event = None
                        async with ActivityContext(container, user_context) as ctx:
                            task_event_service = await ctx.get_task_event_service()

                            # Create event using service - workspace_id and created_by are provided
                            persisted_event = await task_event_service.create_workflow_event(
                                task_id=UUID(task_id),
                                event_type=event["event_type"],
                                data=event["data"],
                                workspace_id=workspace_id,
                                created_by=user_id,
                            )

                            # Commit is handled by the service
                            logger.debug(
                                f"Stored event using service: {event['event_type']} for task {task_id}"
                            )

                        # Publish to the per-task live stream AFTER the DB commit,
                        # using the persisted row id so the read-side dedups the
                        # snapshot(DB) vs live(stream) overlap (ADR-0018). Durable
                        # history stays in task_events; this is the live tail.
                        if persisted_event is not None and dependencies.broker_client is not None:
                            await publish_task_event(
                                dependencies.broker_client,
                                task_id=str(persisted_event.task_id),
                                event_type=persisted_event.event_type,
                                data=persisted_event.data,
                                event_id=str(persisted_event.id),
                                timestamp=persisted_event.timestamp.isoformat()
                                if persisted_event.timestamp
                                else None,
                            )

                    except Exception as db_error:
                        logger.error(f"Failed to store event using service: {db_error}")
                        errors.append(f"DB storage failed for {event['event_type']}: {db_error!s}")

                    # 3. Handle LLM error events locally for immediate action
                    if canonical_type(event["event_type"]) == LLM_FAILED:
                        try:
                            await handle_llm_error_event(domain_event)
                        except Exception as handler_error:
                            logger.error(f"Failed to handle LLM error event: {handler_error}")
                            errors.append(f"Error handler failed: {handler_error!s}")

                    # 4. Durable outbound channel delivery: enqueue directly
                    # to the broker stream. Bypasses the lossy pub/sub bridge
                    # between workflow events and the delivery consumer.
                    # Temporal activity-level retry covers the previously
                    # silent failure window (worker crash between event
                    # receipt and stream submit).
                    if dependencies.broker_client and dependencies.channel_delivery_settings:
                        from agentarea_triggers.channels.activity_emit import (
                            emit_channel_delivery,
                        )

                        # channel_origin source priority:
                        #   1. embedded in event.data (workflow has it inline)
                        #   2. task.parameters via DB lookup (cached per batch)
                        event_data = (
                            event.get("data") if isinstance(event.get("data"), dict) else {}
                        )
                        channel_origin = event_data.get("channel_origin") if event_data else None
                        if not channel_origin and task_id and task_id != "unknown":
                            channel_origin = await _resolve_channel_origin(str(task_id))

                        event_with_id = {
                            "event_type": event["event_type"],
                            "event_id": event.get("event_id"),
                            "task_id": task_id,
                            "data": event["data"],
                        }
                        await emit_channel_delivery(
                            event=event_with_id,
                            channel_origin=channel_origin,
                            broker=dependencies.broker_client,
                            stream=dependencies.channel_delivery_settings.OUTBOUND_STREAM,
                        )

                        # A2A push notifications: one delivery per registered webhook.
                        if task_id and task_id != "unknown":
                            for cfg in await _resolve_push_configs(str(task_id)):
                                cfg_id = cfg.get("id")
                                cfg_url = cfg.get("url")
                                if not cfg_id or not cfg_url:
                                    continue
                                await emit_channel_delivery(
                                    event=event_with_id,
                                    channel_origin={
                                        "type": "a2a_webhook",
                                        "url": cfg_url,
                                        "task_id": str(task_id),
                                        "config_id": cfg_id,
                                        "presentation": "silent",
                                    },
                                    broker=dependencies.broker_client,
                                    stream=dependencies.channel_delivery_settings.OUTBOUND_STREAM,
                                    dedup_suffix=f"a2a:{cfg_id}",
                                )

                    events_published += 1

                except Exception as event_error:
                    logger.error(f"Failed to process single event: {event_error}")
                    errors.append(f"Event processing failed: {event_error!s}")

            return WorkflowEventsResult(
                success=len(errors) == 0,
                events_published=events_published,
                errors=errors,
            )

        except Exception as e:
            logger.error(f"Failed to publish workflow events: {e}")
            return WorkflowEventsResult(
                success=False,
                events_published=0,
                errors=[f"Critical failure: {e!s}"],
            )

    @activity.defn
    async def update_task_status_activity(
        request: UpdateTaskStatusRequest,
    ) -> UpdateTaskStatusResult:
        """Update task status in the database after workflow completion."""
        from uuid import UUID as _UUID

        from agentarea_tasks.infrastructure.repository import TaskRepository

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            session = container._database.async_session_factory()
            ctx._sessions.append(session)
            task_repo = TaskRepository(session, user_context)
            try:
                additional_fields = {}
                if (
                    request.result
                ):  # Task model expects result as dict, but request carries it as JSON string
                    try:
                        result_dict = json.loads(request.result)
                    except (json.JSONDecodeError, TypeError):
                        result_dict = {"response": request.result}
                    if request.total_cost is not None:
                        # Serialize Money (Decimal) to string for JSON compatibility
                        result_dict["total_cost"] = str(request.total_cost)
                    if request.own_cost is not None:
                        result_dict["own_cost"] = str(request.own_cost)
                    additional_fields["result"] = result_dict
                elif request.total_cost is not None or request.own_cost is not None:
                    # Serialize Money (Decimal) to string for JSON compatibility
                    additional_fields["result"] = {}
                    if request.total_cost is not None:
                        additional_fields["result"]["total_cost"] = str(request.total_cost)
                    if request.own_cost is not None:
                        additional_fields["result"]["own_cost"] = str(request.own_cost)
                if request.error_message:
                    # Tasks table stores this as `error`, not `error_message`.
                    additional_fields["error"] = request.error_message

                updated = await task_repo.update_status(
                    _UUID(request.task_id), request.status, **additional_fields
                )
                if updated:
                    return UpdateTaskStatusResult(success=True)
                return UpdateTaskStatusResult(success=False, error="Task not found")
            except Exception as e:
                logger.error(f"Failed to update task status: {e}")
                return UpdateTaskStatusResult(success=False, error=str(e))

    @activity.defn
    async def update_task_governance_snapshot_activity(
        request: UpdateTaskGovernanceSnapshotRequest,
    ) -> UpdateTaskGovernanceSnapshotResult:
        """Persist the policy revision before a waiting workflow resumes."""
        from uuid import UUID as _UUID

        from agentarea_tasks.infrastructure.repository import TaskRepository

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            session = container._database.async_session_factory()
            ctx._sessions.append(session)
            task_repo = TaskRepository(session, user_context)
            task = await task_repo.get_task(_UUID(request.task_id))
            if task is None:
                return UpdateTaskGovernanceSnapshotResult(
                    success=False,
                    error="Task not found",
                )
            metadata = dict(task.metadata or {})
            metadata["governance_snapshot"] = request.governance_snapshot
            updated = await task_repo.update(
                _UUID(request.task_id),
                task_metadata=metadata,
            )
            if updated is None:
                return UpdateTaskGovernanceSnapshotResult(
                    success=False,
                    error="Task not found",
                )
            return UpdateTaskGovernanceSnapshotResult(success=True)

    @activity.defn
    async def check_monthly_spend_cap_activity(
        request: MonthlySpendCapRequest,
    ) -> MonthlySpendCapResult:
        """Read the workspace's month-to-date spend against the run's monthly cap."""
        from agentarea_tasks.infrastructure.repository import TaskRepository

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            session = container._database.async_session_factory()
            ctx._sessions.append(session)
            spent = to_money(await TaskRepository(session, user_context).sum_spend_mtd())
        return MonthlySpendCapResult(
            exceeded=spent >= request.cap_usd,
            month_to_date_usd=spent,
            cap_usd=request.cap_usd,
        )

    @activity.defn
    @auto_heartbeater
    async def compact_messages_activity(
        request: CompactMessagesRequest,
    ) -> CompactMessagesResult:
        """Summarize older messages to reduce context window usage.

        Uses the same model as the agent to generate a concise summary
        of older conversation history, preserving key decisions, tool
        results, and reasoning.
        """
        try:
            model_uuid = UUID(request.model_id)

            if request.workspace_id:
                user_context = create_user_context(request.user_context_data)
            elif request.user_context_data:
                user_context = create_user_context(request.user_context_data)
            else:
                raise ValueError("Either workspace_id or user_context_data must be provided")

            # Dual path: use cached resolved_model if provided, else fall back to DB lookup
            provider_type = None
            model_name = None
            endpoint_url = None
            api_key = None
            max_output_tokens = None
            input_cost_per_token = None
            output_cost_per_token = None

            if request.resolved_model:
                cached = request.resolved_model
                provider_type = cached.get("provider_type")
                model_name = cached.get("model_name")
                endpoint_url = cached.get("endpoint_url")
                max_output_tokens = cached.get("max_output_tokens")
                input_cost_per_token = cached.get("input_cost_per_token")
                output_cost_per_token = cached.get("output_cost_per_token")
                api_key_secret_name = cached.get("api_key_secret")
                if api_key_secret_name:
                    try:
                        api_key = await llm_execution_service.resolve_provider_api_key(
                            reference=api_key_secret_name,
                            managed_by=cached.get("managed_by"),
                            user_context=user_context,
                            secret_manager_factory=dependencies.secret_manager_factory,
                        )
                    except Exception as decrypt_err:
                        logger.warning(
                            f"Failed to decrypt cached API key for model {request.model_id} "
                            f"in compact_messages, falling back to DB lookup: {decrypt_err}",
                            exc_info=True,
                        )
                        provider_type = None

            if provider_type is None:
                async with ActivityContext(container, user_context) as ctx:
                    model_instance_service = await ctx.get_model_instance_service()
                    model_instance = await model_instance_service.get(model_uuid)
                    if not model_instance:
                        raise ModelInstanceNotFoundError(
                            f"Model instance {request.model_id} not found"
                        )

                    provider_type = model_instance.provider_config.provider_spec.provider_type
                    model_name = model_instance.model_spec.model_name
                    # endpoint_url lives on provider_config (ollama, self-hosted, etc.), not model_spec.
                    endpoint_url = getattr(
                        model_instance.provider_config, "endpoint_url", None
                    ) or getattr(model_instance.model_spec, "endpoint_url", None)
                    max_output_tokens = getattr(
                        model_instance.model_spec, "max_output_tokens", None
                    )
                    input_cost_per_token = getattr(
                        model_instance.model_spec, "input_cost_per_token", None
                    )
                    output_cost_per_token = getattr(
                        model_instance.model_spec, "output_cost_per_token", None
                    )

                    api_key_secret_name = getattr(model_instance.provider_config, "api_key", None)
                    if api_key_secret_name:
                        api_key = await llm_execution_service.resolve_provider_api_key(
                            reference=api_key_secret_name,
                            managed_by=getattr(model_instance.provider_config, "managed_by", None),
                            user_context=user_context,
                            secret_manager_factory=dependencies.secret_manager_factory,
                        )

            if input_cost_per_token is None or output_cost_per_token is None:
                raise ValueError(
                    "model pricing is not configured; compaction budget cannot be enforced"
                )

            if endpoint_url:
                local_host = dependencies.settings.app.local_host
                endpoint_url = endpoint_url.replace("localhost", local_host).replace(
                    "127.0.0.1", local_host
                )

            llm_model = LLMModel(
                provider_type=provider_type,
                model_name=str(model_name),
                api_key=api_key,
                endpoint_url=endpoint_url,
                input_cost_per_token=input_cost_per_token,
                output_cost_per_token=output_cost_per_token,
            )

            # Build compaction prompt
            conversation_text = ""
            for msg in request.messages_to_compact:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if msg.get("tool_calls"):
                    tool_names = [
                        tc.get("function", {}).get("name", "?")
                        for tc in msg["tool_calls"]
                        if isinstance(tc, dict)
                    ]
                    content += f" [Called tools: {', '.join(tool_names)}]"
                if msg.get("name"):
                    role = f"tool({msg['name']})"
                conversation_text += f"[{role}]: {content}\n"

            compaction_prompt = (
                "Summarize the following conversation history concisely. Preserve:\n"
                "1. The original task/goal\n"
                "2. Key decisions made and reasoning\n"
                "3. Important tool results and data obtained\n"
                "4. Current state of progress\n"
                "5. Any errors encountered and how they were handled\n\n"
                "Be concise but complete. Use bullet points for key facts.\n\n"
                f"Conversation to summarize:\n{conversation_text}"
            )

            summary_request = LLMRequest(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a conversation summarizer. Create concise, factual "
                            "summaries that preserve all important information for "
                            "continuing the task."
                        ),
                    },
                    {"role": "user", "content": compaction_prompt},
                ],
                max_tokens=llm_execution_service.resolve_llm_max_tokens(
                    requested=None,
                    model_cap=max_output_tokens,
                    effective_policy=request.effective_policy,
                ),
            )

            complete_content = ""
            final_usage = None
            final_cost = ZERO
            async for chunk in llm_model.ainvoke_stream(summary_request):
                if chunk.content:
                    complete_content += chunk.content
                if chunk.usage is not None:
                    final_usage = chunk.usage
                if chunk.cost and chunk.cost > final_cost:
                    final_cost = to_money(chunk.cost)

            if final_usage is None or final_usage.total_tokens <= 0:
                raise RuntimeError(
                    "compaction usage accounting unavailable; budget cannot be enforced"
                )

            original_tokens = sum(
                len(msg.get("content", "") or "") // 4 for msg in request.messages_to_compact
            )
            summary_tokens = len(complete_content) // 4

            return CompactMessagesResult(
                summary=complete_content,
                original_message_count=len(request.messages_to_compact),
                estimated_tokens_saved=max(0, original_tokens - summary_tokens),
                cost=final_cost,
                usage=LLMUsage(
                    prompt_tokens=final_usage.prompt_tokens,
                    completion_tokens=final_usage.completion_tokens,
                    total_tokens=final_usage.total_tokens,
                ),
            )

        except Exception as e:
            logger.error(f"Message compaction failed: {e}")
            from temporalio.exceptions import ApplicationError

            from .event_publisher import _is_non_retryable_error

            raise ApplicationError(
                f"Message compaction failed: {e}",
                type=type(e).__name__,
                non_retryable=_is_non_retryable_error(e),
            ) from e

    @activity.defn
    async def resolve_agent_tools_activity(
        request: ResolveAgentToolsRequest,
    ) -> ResolveAgentToolsResult:
        """Resolve agent names to their IDs for workflow-level delegation."""
        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            agent_service = await ctx.get_agent_service()
            agent_map: dict[str, str] = {}

            for agent_name in request.agent_names:
                try:
                    agent = await agent_service.get_by_name(agent_name)
                    if agent:
                        agent_map[agent_name] = str(agent.id)
                    else:
                        logger.warning(f"Agent '{agent_name}' not found for delegation")
                except Exception as e:
                    logger.error(f"Failed to resolve agent '{agent_name}': {e}")

            return ResolveAgentToolsResult(agent_map=agent_map)

    @activity.defn
    async def recall_history_activity(
        request: RecallHistoryRequest,
    ) -> RecallHistoryResult:
        """Recall context from past task executions via the DB event log (tier 2).

        Allows agents to recover context that was compacted out of the
        working set, or to review what happened in earlier executions.
        """
        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            task_event_service = await ctx.get_task_event_service()

            try:
                # Fetch events, optionally filtered by type
                if request.event_types:
                    events = []
                    for event_type in request.event_types:
                        type_events = await task_event_service.get_events_by_type(
                            event_type=event_type,
                            limit=request.limit,
                        )
                        events.extend(type_events)
                    # Sort by timestamp descending, limit total
                    events.sort(
                        key=lambda e: e.created_at if hasattr(e, "created_at") else "",
                        reverse=True,
                    )
                    events = events[: request.limit]
                else:
                    events = await task_event_service.get_task_events(
                        task_id=request.task_id,
                        limit=request.limit,
                    )

                # Serialize events to dicts
                events_data = []
                for event in events:
                    event_dict = {
                        "event_type": event.event_type,
                        "data": event.data if hasattr(event, "data") else {},
                        "created_at": str(event.timestamp) if hasattr(event, "timestamp") else "",
                    }
                    events_data.append(event_dict)

                # Build a brief summary
                event_type_counts: dict[str, int] = {}
                for e in events_data:
                    t = e.get("event_type", "unknown")
                    event_type_counts[t] = event_type_counts.get(t, 0) + 1

                summary_parts = [f"{count}x {etype}" for etype, count in event_type_counts.items()]
                summary = f"Retrieved {len(events_data)} events: {', '.join(summary_parts)}"

                return RecallHistoryResult(
                    events=events_data,
                    total_count=len(events_data),
                    summary=summary,
                )

            except Exception as e:
                logger.error(f"Failed to recall history for task {request.task_id}: {e}")
                return RecallHistoryResult(
                    summary=f"Failed to recall history: {e}",
                )

    @activity.defn(name="materialize_skill_files_activity")
    async def materialize_skill_files_activity(
        request: MaterializeSkillFilesRequest,
    ) -> MaterializeSkillFilesResult:
        """Copy a skill's bundle into the task's sandbox workspace.

        The sandbox workspace persists for the life of the workflow, so the
        bundle is uploaded once at activation and stays on disk for every later
        shell call. A skill carrying only prose is still a bundle — its text is
        written as SKILL.md, so there is one kind of skill, not two.
        """
        from agentarea_agents.infrastructure.skill_storage_service import (
            SkillStorageService,
        )
        from agentarea_common.artifacts import (
            DbArtifactEventRecorder,
            WorkspaceRepository,
        )

        from .skill_materialization import (
            assemble_skill_bundle,
            build_skill_workspace_files,
            skill_workspace_dir,
        )

        try:
            if not request.workspace_id:
                raise ValueError("skill materialization requires a workspace_id")
            user_context = create_user_context(request.user_context_data)
            async with ActivityContext(container, user_context) as ctx:
                skill_service = await ctx.get_skill_service()
                skill = await skill_service.get_with_catalog(request.skill_id)
                if not skill:
                    return MaterializeSkillFilesResult(
                        success=False, error=f"Skill {request.skill_id} not found"
                    )

                # A skill is a folder. Files may be absent, prose may be absent,
                # but the folder always gets a manifest — there is one kind of
                # skill, not a "content-only" second kind.
                bundled: list[tuple[str, bytes]] = []
                if skill.s3_path:
                    storage_service = SkillStorageService()
                    for info in await storage_service.list_files(skill.s3_path):
                        relative_path = getattr(info, "path", None) or getattr(info, "name", "")
                        if not relative_path:
                            continue
                        bundled.append(
                            (
                                relative_path,
                                await storage_service.get_file_content(
                                    skill.s3_path, relative_path
                                ),
                            )
                        )

                files = assemble_skill_bundle(skill.content, bundled)
                workspace_files = build_skill_workspace_files(
                    request.skill_name, str(request.skill_id), files
                )
                if not workspace_files:
                    return MaterializeSkillFilesResult(
                        success=False,
                        error=f"Skill '{request.skill_name}' bundle contained no usable paths",
                    )

                if not request.workspace_id or not request.task_id:
                    return MaterializeSkillFilesResult(
                        success=False,
                        error="workspace_id and task_id are required for skill materialization",
                    )
                repository = WorkspaceRepository(
                    recorder=DbArtifactEventRecorder(),
                    actor=_agent_artifact_actor(request, user_context),
                )
                await repository.put_files(
                    str(request.workspace_id),
                    str(request.task_id),
                    workspace_files,
                    provenance={
                        "source": "skill",
                        "skill_id": str(request.skill_id),
                        "skill_name": request.skill_name,
                    },
                    owner=request.workflow_id or None,
                )

                directory = skill_workspace_dir(request.skill_name, str(request.skill_id))
                return MaterializeSkillFilesResult(
                    success=True,
                    directory=directory,
                    paths=list(workspace_files),
                )

        except Exception as e:
            logger.error(f"Skill materialization error: {e}", exc_info=True)
            return MaterializeSkillFilesResult(
                success=False, error=f"Failed to materialize skill files: {e}"
            )

    # --- Dynamic Context Discovery Activities ---

    @activity.defn(name="store_context_output")
    async def store_context_output_activity(request: StoreOutputRequest) -> StoreOutputResult:
        """Store a large tool output in MinIO for later retrieval."""
        from ..workflows.context_store import ContextStore

        context_store = ContextStore(workspace_id=request.workspace_id, task_id=request.task_id)
        try:
            await context_store.store_output(request.output_id, request.content)
            return StoreOutputResult(success=True)
        except Exception as e:
            logger.error(f"Failed to store context output {request.output_id}: {e}")
            return StoreOutputResult(success=False, error=str(e))

    @activity.defn(name="read_context_output")
    async def read_context_output_activity(request: ReadOutputRequest) -> ReadOutputResult:
        """Read a stored tool output from MinIO with optional filtering."""
        from ..workflows.context_store import ContextStore

        context_store = ContextStore(workspace_id=request.workspace_id, task_id=request.task_id)
        try:
            content = await context_store.read_output(
                request.output_id, grep=request.grep, head=request.head, tail=request.tail
            )
            return ReadOutputResult(success=True, content=content)
        except Exception as e:
            logger.error(f"Failed to read context output {request.output_id}: {e}")
            return ReadOutputResult(success=False, error=str(e))

    @activity.defn(name="store_history_chunk")
    async def store_history_chunk_activity(request: StoreHistoryRequest) -> StoreHistoryResult:
        """Store compacted messages in MinIO before they are summarized."""
        from ..workflows.context_store import ContextStore

        context_store = ContextStore(workspace_id=request.workspace_id, task_id=request.task_id)
        try:
            await context_store.store_history_chunk(request.chunk_index, request.messages)
            return StoreHistoryResult(success=True)
        except Exception as e:
            logger.error(f"Failed to store history chunk {request.chunk_index}: {e}")
            return StoreHistoryResult(success=False, error=str(e))

    @activity.defn(name="search_history")
    async def search_history_activity(request: SearchHistoryRequest) -> SearchHistoryResult:
        """Search stored history chunks in MinIO."""
        from ..workflows.context_store import ContextStore

        context_store = ContextStore(workspace_id=request.workspace_id, task_id=request.task_id)
        try:
            results = await context_store.search_history(
                grep=request.grep, tool_name=request.tool_name
            )
            return SearchHistoryResult(success=True, results=results)
        except Exception as e:
            logger.error(f"Failed to search history: {e}")
            return SearchHistoryResult(success=False, error=str(e))

    @activity.defn
    async def create_delegation_task_activity(
        request: CreateDelegationTaskRequest,
    ) -> CreateDelegationTaskResult:
        """Create a task record in DB for agent delegation."""
        try:
            from agentarea_common.base.repository_factory import RepositoryFactory
            from agentarea_common.config import get_database
            from agentarea_governance.domain.policies import (
                BudgetPolicy,
                PolicyDocument,
                effective_policy_from_json,
            )
            from agentarea_tasks.infrastructure.repository import TaskRepository
            from agentarea_tasks.task_service import TaskService
            from agentarea_tasks.temporal_task_manager import TemporalTaskManager

            if request.parent_effective_policy is None:
                raise ValueError(
                    "delegation request is missing the parent effective-policy snapshot"
                )
            parent_effective_policy = effective_policy_from_json(request.parent_effective_policy)
            parent_effective_policy.require_runtime_contract()
            if request.run_budget_usd is None:
                raise ValueError("delegation request is missing its allocated run budget")

            database = get_database()
            async with database.async_session_factory() as session:
                user_context = UserContext(
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                )
                repository_factory = RepositoryFactory(session, user_context)
                task_repository = repository_factory.create_repository(TaskRepository)
                task_manager = TemporalTaskManager(
                    task_repository=task_repository,
                    temporal_executor=dependencies.workflow_executor,
                )

                task_service = TaskService(
                    repository_factory=repository_factory,
                    event_broker=dependencies.event_broker,
                    task_manager=task_manager,
                )

                task = await task_service.create_task_with_policy(
                    agent_id=UUID(request.target_agent_id),
                    description=f"Delegated task to {request.target_agent_name}",
                    workspace_id=request.workspace_id,
                    user_id=request.user_id,
                    title="Delegation from agent",
                    query=request.message,
                    parameters={
                        "source": "agent_delegation",
                        "parent_agent_id": request.parent_agent_id,
                        "parent_task_id": request.parent_task_id,
                    },
                    metadata_overrides={
                        "created_via": "agent_delegation",
                        "parent_agent_id": request.parent_agent_id,
                        "parent_task_id": request.parent_task_id,
                    },
                    task_policy=PolicyDocument(
                        budget=BudgetPolicy(
                            run_budget_usd=request.run_budget_usd,
                        )
                    ),
                    upper_bound_policy=parent_effective_policy,
                    require_model=True,
                )

                logger.info(
                    f"Created delegation task {task.id} for agent {request.target_agent_name}"
                )

                return CreateDelegationTaskResult(
                    task_id=task.id,
                    status="created",
                    effective_policy=task.effective_policy,
                )

        except Exception as e:
            logger.error(f"Failed to create delegation task: {e}", exc_info=True)
            raise

    # Return all activity functions
    return [
        discover_runtime_manifest_activity,
        validate_artifacts_activity,
        build_agent_config_activity,
        discover_available_tools_activity,
        discover_tool_providers_activity,
        resolve_model_activity,
        call_llm_activity,
        execute_mcp_tool_activity,
        create_execution_plan_activity,
        evaluate_goal_progress_activity,
        publish_workflow_events_activity,
        compact_messages_activity,
        resolve_agent_tools_activity,
        recall_history_activity,
        update_task_status_activity,
        update_task_governance_snapshot_activity,
        check_monthly_spend_cap_activity,
        materialize_skill_files_activity,
        store_context_output_activity,
        read_context_output_activity,
        store_history_chunk_activity,
        search_history_activity,
        create_delegation_task_activity,
    ]
