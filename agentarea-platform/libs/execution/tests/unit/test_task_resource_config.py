"""Run resource selections affect execution without editing the saved agent."""

import hashlib
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents_sdk.tools.tool_manager import DiscoveryResult, ProviderDiscovery
from agentarea_common.auth.context import UserContext
from agentarea_execution.activities import agent_execution_activities as activities
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentConfigResult,
    DiscoverToolProvidersResult,
    RuntimeDiscoveryResult,
    ToolDefinition,
    ToolDiscoveryRequest,
    ToolDiscoveryResult,
)
from temporalio.exceptions import ApplicationError


def skill(name="Research"):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        description="Canonical description",
        content="# Instructions",
        s3_path=None,
    )


def agent(*, tools=None, skills=None):
    return SimpleNamespace(
        id=uuid4(),
        name="Coordinator",
        description="Coordinate work",
        instruction="Do the task",
        model_id=str(uuid4()),
        tools=tools or [],
        skills=skills or [],
        events_config={},
        planning=False,
        a2ui_enabled=False,
        agent_type="stateful",
    )


def context():
    ctx = AsyncMock()
    ctx.get_mcp_server_instance_service.return_value.get.return_value = None
    ctx.get_skill_service.return_value.get_with_catalog.return_value = None
    return ctx


@pytest.mark.parametrize("reference_kind", ["name", "uuid", "uppercase_uuid"])
@pytest.mark.asyncio
async def test_same_mcp_never_widens_inherited_tool_permissions(reference_kind):
    instance = SimpleNamespace(id=uuid4(), name="GitHub")
    reference = {
        "name": instance.name,
        "uuid": str(instance.id),
        "uppercase_uuid": str(instance.id).upper(),
    }[reference_kind]
    saved = agent(
        tools=[
            {
                "type": "mcp",
                "name": reference,
                "settings": {
                    "allowed_tools": [{"tool_name": "read", "requires_user_confirmation": True}]
                },
            }
        ]
    )
    before = deepcopy(saved.tools)
    ctx = context()
    ctx.get_mcp_server_instance_service.return_value.get.return_value = instance

    tools, _ = await activities._resolve_task_resources(
        saved, {"mcps": [{"id": str(instance.id), "name": "Ignore all limits"}]}, ctx
    )

    assert tools == before
    tools[0]["settings"]["allowed_tools"].clear()
    assert saved.tools == before


@pytest.mark.asyncio
async def test_additions_are_canonical_and_deduplicated_without_mutating_agent():
    instance = SimpleNamespace(id=uuid4(), name="GitHub")
    attached = skill("Attached")
    selected = skill()
    saved = agent(skills=[attached])
    ctx = context()
    ctx.get_mcp_server_instance_service.return_value.get.return_value = instance
    ctx.get_skill_service.return_value.get_with_catalog.return_value = selected

    tools, skills = await activities._resolve_task_resources(
        saved,
        {
            "mcps": [
                {"id": str(instance.id), "name": "Injected", "settings": {"allowed_tools": []}},
                str(instance.id),
            ],
            "skills": [
                str(attached.id),
                {"id": str(selected.id), "content": "Injected"},
                str(selected.id),
            ],
        },
        ctx,
    )

    assert tools == [{"type": "mcp", "name": str(instance.id)}]
    assert skills == [attached, selected]
    assert skills[-1].content == "# Instructions"
    assert saved.tools == []
    assert saved.skills == [attached]
    ctx.get_skill_service.return_value.get_with_catalog.assert_awaited_once_with(selected.id)
    ctx.get_mcp_server_instance_service.return_value.get.assert_awaited_once_with(instance.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["mcps", "skills"])
async def test_unavailable_or_cross_workspace_resource_fails_closed(kind):
    with pytest.raises(ApplicationError, match="unavailable") as error:
        await activities._resolve_task_resources(agent(), {kind: [str(uuid4())]}, context())
    assert error.value.non_retryable


@pytest.mark.asyncio
async def test_same_name_different_skill_does_not_replace_attached_instructions():
    ctx = context()
    selected = skill()
    ctx.get_skill_service.return_value.get_with_catalog.return_value = selected
    with pytest.raises(ApplicationError, match="distinct names"):
        await activities._resolve_task_resources(
            agent(skills=[skill()]), {"skills": [str(selected.id)]}, ctx
        )


@pytest.mark.parametrize("kind", ["mcps", "skills"])
@pytest.mark.parametrize("value", ["all", ["name-only"], [{}], [None], [12]])
def test_malformed_task_resource_refs_are_rejected(kind, value):
    with pytest.raises(ApplicationError) as error:
        activities._task_resource_ids({kind: value}, kind)
    assert error.value.non_retryable


@pytest.mark.parametrize("alias", ["mcps", "mcp", "mcp_servers"])
def test_legacy_mcp_aliases_keep_the_same_identity(alias):
    instance_id = uuid4()
    assert activities._task_resource_ids({alias: [{"instance_id": str(instance_id)}]}, "mcps") == [
        instance_id
    ]


def test_legacy_activity_requests_have_safe_defaults():
    params = {"agent_id": uuid4(), "user_context_data": {"workspace_id": "workspace"}}
    assert AgentConfigRequest(**params).task_parameters == {}
    assert ToolDiscoveryRequest(**params).tools is None
    assert ToolDiscoveryRequest(**params, tools=[]).tools == []


@pytest.fixture
def activity_context(monkeypatch):
    from agentarea_execution.activities import dependencies

    ctx = context()
    ctx.__aenter__.return_value = ctx
    monkeypatch.setattr(dependencies, "ActivityServiceContainer", MagicMock())
    monkeypatch.setattr(dependencies, "ActivityContext", MagicMock(return_value=ctx))
    monkeypatch.setattr(
        activities, "fetch_runtime_manifest", AsyncMock(return_value=RuntimeDiscoveryResult())
    )
    monkeypatch.setattr(activities, "_record_task_config_hash", AsyncMock())
    all_activities = {fn.__name__: fn for fn in activities.make_agent_activities(MagicMock())}
    return ctx, all_activities


@pytest.mark.asyncio
async def test_config_activity_uses_selected_skills_and_mcp_in_run_hash(activity_context):
    ctx, functions = activity_context
    saved = agent()
    selected_skill = skill()
    instance = SimpleNamespace(id=uuid4(), name="GitHub")
    ctx.get_agent_service.return_value.get_with_skills.return_value = saved
    ctx.get_mcp_server_instance_service.return_value.get.return_value = instance
    ctx.get_skill_service.return_value.get_with_catalog.return_value = selected_skill
    ctx.get_model_instance_service.return_value.get.return_value = SimpleNamespace(
        model_spec=SimpleNamespace(context_window=64000, default_context_strategy="static")
    )
    request = AgentConfigRequest(
        agent_id=saved.id,
        user_context_data={"user_id": "user", "workspace_id": "workspace"},
    )
    inherited = await functions["build_agent_config_activity"](request)
    request.task_parameters = {
        "skills": [{"id": str(selected_skill.id), "name": "Forged name"}],
        "mcps": [str(instance.id)],
    }
    result = await functions["build_agent_config_activity"](request)

    assert result.tools == [{"type": "mcp", "name": str(instance.id)}]
    assert result.skills[0].name == selected_skill.name
    assert result.skills[0].content == selected_skill.content
    assert result.config_hash != inherited.config_hash
    assert saved.skills == []
    assert saved.tools == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["discover_available_tools_activity", "discover_tool_providers_activity"]
)
@pytest.mark.parametrize("run_tools", [None, [], [{"type": "mcp", "name": "selected-server"}]])
async def test_both_discovery_modes_use_resolved_run_tools(
    activity_context, monkeypatch, mode, run_tools
):
    ctx, functions = activity_context
    saved = agent(tools=[{"type": "mcp", "name": "saved-server"}])
    ctx.get_agent_service.return_value.get.return_value = saved
    manager = MagicMock()
    manager.discover_available_tools_split = AsyncMock(
        return_value=DiscoveryResult(explicit_tools=[], searchable_entries=[])
    )
    manager.discover_tool_providers = AsyncMock(return_value=ProviderDiscovery())
    monkeypatch.setattr(activities, "ToolManager", MagicMock(return_value=manager))

    await functions[mode](
        ToolDiscoveryRequest(
            agent_id=saved.id,
            user_context_data={"user_id": "user", "workspace_id": "workspace"},
            tools=run_tools,
        )
    )

    method = (
        manager.discover_available_tools_split
        if "available" in mode
        else manager.discover_tool_providers
    )
    assert method.await_args.kwargs["tools_config"] == (
        saved.tools if run_tools is None else run_tools
    )


@pytest.fixture
def file_storage(monkeypatch):
    import agentarea_common.artifacts as artifacts

    repository = AsyncMock()
    stored = {}
    sources = {}

    async def read(workspace_id, task_id, path):
        if (workspace_id, task_id, path) not in stored:
            raise FileNotFoundError(path)
        return stored[(workspace_id, task_id, path)]

    async def put(workspace_id, task_id, files, **kwargs):
        for path, data in files.items():
            stored[(workspace_id, task_id, path)] = (data, kwargs["content_types"][path])

    service = AsyncMock()

    async def read_source(workspace_id, path):
        if (workspace_id, path) not in sources:
            raise FileNotFoundError(path)
        return sources[(workspace_id, path)], "text/plain"

    async def head(workspace_id, path):
        data = sources.get((workspace_id, path))
        if data is None:
            return None
        return {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "content_type": "text/plain",
        }

    repository.get.side_effect = read
    repository.put_files.side_effect = put
    service.get.side_effect = read_source
    service.head.side_effect = head
    monkeypatch.setattr(artifacts, "WorkspaceRepository", MagicMock(return_value=repository))
    monkeypatch.setattr(artifacts, "ArtifactService", MagicMock(return_value=service))
    return repository, service, stored, sources


def file_request(paths):
    return AgentConfigRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        task_parameters={"files": paths},
        user_context_data={"user_id": "user", "workspace_id": "workspace"},
    )


@pytest.mark.asyncio
async def test_files_snapshot_regular_and_task_inputs_and_retries_reuse_snapshot(file_storage):
    repository, service, stored, sources = file_storage
    source_task = str(uuid4())
    source_path = f"tasks/{source_task}/workspace/report.txt"
    sources[("workspace", "notes.txt")] = b"notes"
    stored[("workspace", source_task, "report.txt")] = (b"report", "text/plain")
    request = file_request(["notes.txt", source_path, "notes.txt"])
    user = UserContext(user_id="user", workspace_id="workspace")

    first = await activities._prepare_task_files(request, user)
    sources.clear()
    del stored[("workspace", source_task, "report.txt")]
    second = await activities._prepare_task_files(request, user)

    assert first == second
    assert len(first) == 2
    assert all(item["relative_path"].startswith("inputs/attachments/") for item in first)
    assert {item["sha256"] for item in first} == {
        hashlib.sha256(b"notes").hexdigest(),
        hashlib.sha256(b"report").hexdigest(),
    }
    repository.attach_object.assert_not_awaited()
    assert repository.put_files.await_count == 2
    service.head.assert_awaited_once_with("workspace", "notes.txt")


@pytest.mark.asyncio
async def test_empty_selected_workspace_file_is_a_valid_snapshot(file_storage):
    _, _, stored, sources = file_storage
    sources[("workspace", "empty.txt")] = b""
    request = file_request(["empty.txt"])
    result = await activities._prepare_task_files(
        request, UserContext(user_id="user", workspace_id="workspace")
    )
    assert result[0]["size"] == 0
    assert result[0]["sha256"] == hashlib.sha256(b"").hexdigest()
    assert stored[("workspace", str(request.task_id), result[0]["relative_path"])][0] == b""


@pytest.mark.asyncio
async def test_source_changed_between_head_and_read_never_poisons_snapshot(file_storage):
    repository, service, stored, sources = file_storage
    sources[("workspace", "notes.txt")] = b"before"
    service.get.side_effect = None
    service.get.return_value = (b"after", "text/plain")
    with pytest.raises(ApplicationError, match="unavailable"):
        await activities._prepare_task_files(
            file_request(["notes.txt"]), UserContext(user_id="user", workspace_id="workspace")
        )
    repository.put_files.assert_not_awaited()
    assert stored == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        ".",
        "../secret",
        "/other-workspace/secret",
        "notes/../secret",
        "notes//secret",
        "notes\\secret",
        "staging/secret",
        ".trash/secret",
        "tasks/abc/objects/secret",
        "tasks/abc/workspace/secret",
        "s3://other-workspace/secret",
        "notes\nsecret",
        None,
    ],
)
async def test_file_selection_rejects_traversal_hidden_and_noncanonical_paths(file_storage, path):
    repository, service, _, _ = file_storage
    with pytest.raises(ApplicationError, match="Invalid task file path") as error:
        await activities._prepare_task_files(
            file_request([path]), UserContext(user_id="user", workspace_id="workspace")
        )
    assert error.value.non_retryable
    repository.get.assert_not_awaited()
    service.head.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("is_task_file", [False, True])
async def test_files_in_other_workspace_are_unavailable(file_storage, is_task_file):
    repository, _service, stored, sources = file_storage
    source_task = str(uuid4())
    path = f"tasks/{source_task}/workspace/private.txt" if is_task_file else "private.txt"
    sources[("another-workspace", "private.txt")] = b"private"
    stored[("another-workspace", source_task, "private.txt")] = (b"private", "text/plain")
    with pytest.raises(ApplicationError, match="unavailable") as error:
        await activities._prepare_task_files(
            file_request([path]), UserContext(user_id="user", workspace_id="workspace")
        )
    assert error.value.non_retryable
    repository.attach_object.assert_not_awaited()
    repository.put_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_config_returns_trusted_attachment_descriptors(activity_context, file_storage):
    ctx, functions = activity_context
    _, _, _, sources = file_storage
    sources[("workspace", "notes.txt")] = b"notes"
    saved = agent()
    ctx.get_agent_service.return_value.get_with_skills.return_value = saved
    ctx.get_model_instance_service.return_value.get.return_value = SimpleNamespace(
        model_spec=SimpleNamespace(context_window=64000, default_context_strategy="static")
    )
    request = file_request(["notes.txt"])
    request.agent_id = saved.id
    request.execution_context = {"project_id": "project"}

    result = await functions["build_agent_config_activity"](request)

    assert result.execution_context["project_id"] == "project"
    assert result.execution_context["workspace_attachments"][0]["size"] == 5
    assert request.execution_context == {"project_id": "project"}


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["static", "dynamic"])
async def test_workflow_forwards_selections_and_keeps_policy_filtering(monkeypatch, strategy):
    from agentarea_execution.workflows import agent_execution_workflow as workflow_module
    from agentarea_execution.workflows.constants import Activities

    instance_id = str(uuid4())
    run_tools = [{"type": "mcp", "name": instance_id}]
    request_parameters = {"mcps": [instance_id], "files": ["notes.txt"]}
    metadata = {"project_id": "project", "workspace_attachments": [{"filename": "notes.txt"}]}
    config = AgentConfigResult(
        id=str(uuid4()),
        name="Coordinator",
        description="",
        instruction="Do the task",
        model_id="",
        context_window=64000,
        default_context_strategy=strategy,
        tools=run_tools,
        execution_context=metadata,
    )
    seen = {}

    async def execute_activity(name, *, args, **kwargs):
        seen[name] = args[0]
        if name == Activities.BUILD_AGENT_CONFIG:
            return config
        if name == Activities.DISCOVER_AVAILABLE_TOOLS:
            return ToolDiscoveryResult(
                tools=[
                    ToolDefinition(
                        function={
                            "name": "restricted_action",
                            "description": "Restricted action",
                            "parameters": {},
                        }
                    )
                ]
            )
        if name == Activities.DISCOVER_TOOL_PROVIDERS:
            return DiscoverToolProvidersResult(providers=[])
        raise AssertionError(f"Unexpected activity: {name}")

    monkeypatch.setattr(workflow_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflow_module.workflow, "logger", MagicMock())
    flow = workflow_module.AgentExecutionWorkflow()
    flow.state.agent_id = config.id
    flow.state.task_id = str(uuid4())
    flow.state.user_id = "user"
    flow.state.workspace_id = "workspace"
    flow.state.goal = workflow_module.AgentGoal(
        id="goal",
        description="Work",
        context=request_parameters,
        success_criteria=[],
        max_iterations=10,
        requires_human_approval=False,
    )
    flow.state.effective_policy = {"tools": {"denied": ["restricted_action"]}}
    flow.event_manager = MagicMock()
    flow._publish_events_immediately = AsyncMock()

    await flow._initialize_agent_config()

    assert seen[Activities.BUILD_AGENT_CONFIG].task_parameters == request_parameters
    discovery = (
        Activities.DISCOVER_AVAILABLE_TOOLS
        if strategy == "static"
        else Activities.DISCOVER_TOOL_PROVIDERS
    )
    assert seen[discovery].tools == run_tools
    assert flow._workflow_metadata == metadata
    assert flow.state.agent_config["tools"] == run_tools
    assert "restricted_action" not in {
        tool["function"]["name"] for tool in flow.state.available_tools
    }
