"""Agent configuration and tool discovery for a run."""

import hashlib
import logging
from collections.abc import Callable
from copy import deepcopy
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_agents.domain.config_hash import compute_agent_config_hash
from agentarea_agents_sdk import ToolManager
from agentarea_common.auth.context import UserContext
from temporalio import activity
from temporalio.exceptions import ApplicationError

from ...exceptions import AgentNotFoundError, ModelInstanceNotFoundError, NoModelBoundError
from ...interfaces import ActivityDependencies
from ...models import (
    AgentConfigRequest,
    AgentConfigResult,
    DiscoverToolProvidersResult,
    McpToolRoute,
    ResolveAgentToolsRequest,
    ResolveAgentToolsResult,
    RuntimeDiscoveryResult,
    SearchableToolEntry,
    SkillInfo,
    ToolDefinition,
    ToolDiscoveryRequest,
    ToolDiscoveryResult,
    ToolProviderData,
)
from ..runtime_discovery import fetch_runtime_manifest, render_runtime_prompt, runtime_event_data

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


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


def make_config_activities(
    dependencies: ActivityDependencies, container: "ActivityServiceContainer"
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext, create_user_context

    @activity.defn
    async def discover_runtime_manifest_activity() -> RuntimeDiscoveryResult:
        """Discover the manifest exposed by the active sandbox data plane."""
        return await fetch_runtime_manifest(dependencies.settings.mcp.MCP_MANAGER_URL)

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

    return [
        discover_runtime_manifest_activity,
        build_agent_config_activity,
        discover_available_tools_activity,
        discover_tool_providers_activity,
        resolve_agent_tools_activity,
    ]
