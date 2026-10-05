"""Unit tests for canonical workspace bundle export."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from agentarea_agents.application import workspace_export_service
from agentarea_agents.application.workspace_export_service import WorkspaceExportService
from agentarea_bundles.application.analyzer import parse_bundle
from agentarea_bundles.schemas.bundle import setup_refs
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from fastapi import HTTPException

WORKSPACE = "test-workspace"


@pytest.fixture(autouse=True)
def _authorization():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


@pytest.fixture
def mock_agent_service():
    service = MagicMock()
    service.list = AsyncMock(return_value=[])
    service.get_with_skills = AsyncMock(return_value=None)
    return service


@pytest.fixture
def mock_repository_factory():
    factory = MagicMock()
    factory.user_context = UserContext(
        user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE]
    )
    return factory


@pytest.fixture
def mock_mcp_instance_service():
    service = MagicMock()
    service.list = AsyncMock(return_value=[])
    service.get_transport_spec_for_instance = AsyncMock(return_value={})
    return service


@pytest.fixture
def mock_skill_service():
    service = MagicMock()
    service.list = AsyncMock(return_value=[])
    return service


@pytest.fixture
def export_service(
    mock_agent_service,
    mock_repository_factory,
    mock_mcp_instance_service,
    mock_skill_service,
    monkeypatch,
):
    monkeypatch.setattr(
        workspace_export_service,
        "load_workspace",
        AsyncMock(return_value=SimpleNamespace(name="Test Workspace", slug=WORKSPACE)),
    )
    return WorkspaceExportService(
        agent_service=mock_agent_service,
        repository_factory=mock_repository_factory,
        mcp_instance_service=mock_mcp_instance_service,
        skill_service=mock_skill_service,
    )


def _agent(name: str, *, tools=None, skills=None, registry_item_id=None, is_catalog=False):
    return SimpleNamespace(
        id=uuid4(),
        workspace_id=WORKSPACE,
        registry_item_id=registry_item_id,
        is_catalog=is_catalog,
        slug=name.lower().replace(" ", "-"),
        name=name,
        instruction=f"Instructions for {name}",
        model_id="gpt-4o",
        tools=tools or [],
        skills=skills or [],
    )


def _skill(
    name: str,
    *,
    content: str | None = None,
    source_url: str | None = None,
    source_type: str = "content",
):
    return SimpleNamespace(
        id=uuid4(),
        workspace_id=WORKSPACE,
        registry_item_id=None,
        is_catalog=False,
        slug=name.lower().replace(" ", "-"),
        name=name,
        content=content,
        source_type=source_type,
        source_url=source_url,
    )


def _mcp_instance(name: str, *, secret_names=(), instance_id: UUID | None = None):
    return SimpleNamespace(
        id=instance_id or uuid4(),
        workspace_id=WORKSPACE,
        registry_item_id=None,
        is_catalog=False,
        name=name,
        server_spec_id=str(uuid4()),
        json_spec={},
        get_configured_env_vars=lambda: list(secret_names),
    )


class TestExportWorkspace:
    @pytest.mark.asyncio
    async def test_a_member_cannot_export_the_workspace(
        self, export_service, mock_repository_factory, mock_agent_service
    ):
        mock_repository_factory.user_context = UserContext(
            user_id="user-member", workspace_id=WORKSPACE, admin_workspaces=[]
        )

        with pytest.raises(HTTPException) as refused:
            await export_service.export_workspace()

        assert refused.value.status_code == 403
        mock_agent_service.list.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_uses_canonical_bundle_schema_and_stable_keys(
        self, export_service, mock_agent_service
    ):
        mock_agent_service.list.return_value = [
            _agent("Test Agent", tools=[{"type": "code", "name": "agentarea/math"}])
        ]

        yaml_text = await export_service.export_workspace()
        bundle = parse_bundle(yaml_text)

        assert bundle.name == WORKSPACE
        assert bundle.display_name == "Test Workspace"
        assert len(bundle.agents) == 1
        assert bundle.agents[0].key.startswith("agent_test_agent_")
        assert bundle.agents[0].toolsets == ["agentarea/math"]
        assert bundle.mcps == []
        assert "provider_configs" not in yaml_text

    @pytest.mark.asyncio
    async def test_export_skips_catalog_agents_and_keeps_forked_agents(
        self, export_service, mock_agent_service
    ):
        mock_agent_service.list.return_value = [
            _agent("Workspace Agent"),
            _agent("Catalog Agent", is_catalog=True, registry_item_id="ri-catalog"),
            _agent("Forked Agent", registry_item_id="ri-source"),
        ]

        bundle = parse_bundle(await export_service.export_workspace())

        assert [agent.name for agent in bundle.agents] == ["Workspace Agent", "Forked Agent"]

    @pytest.mark.asyncio
    async def test_export_mcp_transport_and_setup_references_never_include_secrets(
        self, export_service, mock_mcp_instance_service
    ):
        instance = SimpleNamespace(
            id=UUID("a1b2c3d4-e5f6-789a-bcde-123456789abc"),
            workspace_id=WORKSPACE,
            registry_item_id=None,
            is_catalog=False,
            name="Test Filesystem",
            server_spec_id="a1b2c3d4-e5f6-789a-bcde-123456789abc",
            json_spec={"TOKEN": "MCP_SECRET_CANARY"},
            get_configured_env_vars=lambda: ["ROOT", "TOKEN"],
        )
        mock_mcp_instance_service.list.return_value = [instance]
        mock_mcp_instance_service.get_transport_spec_for_instance.return_value = {
            "type": "url",
            "endpoint_url": "https://mcp.example.test/sse",
            "TOKEN": "MCP_SECRET_CANARY",
        }

        yaml_text = await export_service.export_workspace()
        bundle = parse_bundle(yaml_text)

        assert len(bundle.mcps) == 1
        assert bundle.mcps[0].name == "Test Filesystem"
        assert bundle.mcps[0].json_spec == {
            "type": "url",
            "endpoint_url": "https://mcp.example.test/sse",
        }
        assert set(bundle.mcps[0].bindings) == {"ROOT", "TOKEN"}
        assert all(value.startswith("${setup.") for value in bundle.mcps[0].bindings.values())
        assert {field.type.value for field in bundle.setup} == {"secret"}
        assert "MCP_SECRET_CANARY" not in yaml_text
        assert "server_spec_id" not in yaml_text

    @pytest.mark.asyncio
    async def test_export_without_optional_services_is_a_valid_bundle(self, export_service):
        service = WorkspaceExportService(
            agent_service=export_service.agent_service,
            repository_factory=export_service.repository_factory,
        )

        bundle = parse_bundle(await service.export_workspace())

        assert bundle.agents == []
        assert bundle.mcps == []
        assert bundle.skills == []
        assert bundle.automations == []
        assert bundle.channels == []


class TestSkillExport:
    @pytest.mark.asyncio
    async def test_export_skills_as_installable_inline_content(
        self, export_service, mock_skill_service
    ):
        mock_skill_service.list.return_value = [
            _skill("Export Skill", content="# Export Skill\nContent here"),
        ]

        bundle = parse_bundle(await export_service.export_workspace())

        assert [skill.name for skill in bundle.skills] == ["Export Skill"]
        assert bundle.skills[0].source_type == "content"
        assert bundle.skills[0].content == "# Export Skill\nContent here"

    @pytest.mark.asyncio
    async def test_github_skill_exports_its_repository_not_a_lossy_copy(
        self, export_service, mock_skill_service
    ):
        # Inline content would carry SKILL.md only and lose the packaged files.
        url = "https://github.com/owner/repo/tree/main/skills/review"
        mock_skill_service.list.return_value = [
            _skill("GitHub Skill", content="# Local copy", source_url=url, source_type="github"),
        ]

        bundle = parse_bundle(await export_service.export_workspace())

        assert bundle.skills[0].source_type == "github"
        assert bundle.skills[0].source_url == url
        assert bundle.skills[0].content is None

    @pytest.mark.asyncio
    async def test_export_fails_for_skill_without_installable_content(
        self, export_service, mock_skill_service
    ):
        mock_skill_service.list.return_value = [
            _skill("Remote Skill", source_url="https://github.com/owner/repo")
        ]

        with pytest.raises(ValueError, match="inline content"):
            await export_service.export_workspace()

    @pytest.mark.asyncio
    async def test_agent_references_exported_skill_key(
        self, export_service, mock_agent_service, mock_skill_service
    ):
        skill = _skill("Attached Skill", content="# Content")
        mock_skill_service.list.return_value = [skill]
        mock_agent_service.list.return_value = [_agent("Agent with Skill", skills=[skill])]

        bundle = parse_bundle(await export_service.export_workspace())

        assert bundle.agents[0].skills == [bundle.skills[0].key]


class TestMcpExport:
    @pytest.mark.asyncio
    async def test_agent_mcp_referenced_by_instance_id_or_name_is_kept(
        self, export_service, mock_agent_service, mock_mcp_instance_service
    ):
        # The webapp stores an attached MCP by instance id; the API also accepts names.
        github = _mcp_instance("GitHub")
        search = _mcp_instance("Search")
        mock_mcp_instance_service.list.return_value = [github, search]
        mock_mcp_instance_service.get_transport_spec_for_instance.return_value = {
            "type": "url",
            "endpoint_url": "https://mcp.example.test/mcp",
        }
        mock_agent_service.list.return_value = [
            _agent(
                "Agent",
                tools=[
                    {"type": "mcp", "name": str(github.id)},
                    {"type": "mcp", "name": "Search"},
                ],
            )
        ]

        bundle = parse_bundle(await export_service.export_workspace())

        keys = {mcp.name: mcp.key for mcp in bundle.mcps}
        assert bundle.agents[0].mcps == [keys["GitHub"], keys["Search"]]

    @pytest.mark.asyncio
    async def test_an_unresolvable_agent_mcp_refuses_the_export(
        self, export_service, mock_agent_service
    ):
        mock_agent_service.list.return_value = [
            _agent("Agent", tools=[{"type": "mcp", "name": "deleted-connection"}])
        ]

        with pytest.raises(ValueError, match="deleted-connection"):
            await export_service.export_workspace()

    @pytest.mark.asyncio
    async def test_a_builtin_mcp_reference_is_not_an_error(
        self, export_service, mock_agent_service, mock_mcp_instance_service
    ):
        builtin = _mcp_instance("Platform Search")
        builtin.is_catalog = True
        mock_mcp_instance_service.list.return_value = [builtin]
        mock_agent_service.list.return_value = [
            _agent("Agent", tools=[{"type": "mcp", "name": "Platform Search"}])
        ]

        bundle = parse_bundle(await export_service.export_workspace())

        assert bundle.mcps == []
        assert bundle.agents[0].mcps == []

    @pytest.mark.asyncio
    async def test_plain_configuration_is_exported_and_credentials_become_setup_fields(
        self, export_service, mock_mcp_instance_service
    ):
        mock_mcp_instance_service.list.return_value = [
            _mcp_instance("Postgres", secret_names=["PGPASSWORD"])
        ]
        mock_mcp_instance_service.get_transport_spec_for_instance.return_value = {
            "type": "command",
            "command": "npx",
            "args": [
                "-y",
                "@modelcontextprotocol/server-postgres",
                "postgresql://app:CANARY_URL@db.internal:5432/app",  # pragma: allowlist secret
                "--api-key=CANARY_FLAG",
                "--token",
                "CANARY_NEXT",
                "--header",
                "Authorization: Bearer CANARY_HEADER",
                "--read-only",
                "https://docs.example.test/schema.json",
            ],
            "environment": {
                "MODE": "readonly",
                "ROOT": "/data",
                "SERVICE_TOKEN": "CANARY_ENV_NAME",
                "UPSTREAM": "https://user:CANARY_ENV_URL@upstream.test",  # pragma: allowlist secret
            },
            "env_vars": ["PGPASSWORD"],
        }

        yaml_text = await export_service.export_workspace()
        bundle = parse_bundle(yaml_text)

        assert "CANARY" not in yaml_text
        mcp = bundle.mcps[0]
        args = mcp.json_spec["args"]
        assert args[:2] == ["-y", "@modelcontextprotocol/server-postgres"]
        assert args[2].startswith("${setup.")
        assert args[3].startswith("--api-key=${setup.")
        assert args[4] == "--token"
        assert args[5].startswith("${setup.")
        assert args[6] == "--header"
        assert args[7].startswith("Authorization: ${setup.")
        assert args[8:] == ["--read-only", "https://docs.example.test/schema.json"]
        assert mcp.json_spec["environment"] == {"MODE": "readonly", "ROOT": "/data"}
        assert set(mcp.bindings) == {"PGPASSWORD", "SERVICE_TOKEN", "UPSTREAM"}

        secret_keys = {field.key for field in bundle.setup if field.type.value == "secret"}
        referenced = {ref for value in [*args, *mcp.bindings.values()] for ref in setup_refs(value)}
        assert referenced == secret_keys
        assert len(secret_keys) == 7
        # Deterministic: the same workspace exports the same document.
        assert await export_service.export_workspace() == yaml_text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "endpoint_url",
        [
            "https://mcp.example.test/sse?api_key=CANARY",
            "https://user:CANARY@mcp.example.test/sse",  # pragma: allowlist secret
            "https://mcp.example.test/api/mcp/s/CANARYx9aB3cD4eF5gH6iJ7kL8/mcp",
        ],
    )
    async def test_a_credentialed_endpoint_url_becomes_a_secret_setup_field(
        self, export_service, mock_mcp_instance_service, endpoint_url
    ):
        mock_mcp_instance_service.list.return_value = [_mcp_instance("Hosted")]
        mock_mcp_instance_service.get_transport_spec_for_instance.return_value = {
            "type": "url",
            "endpoint_url": endpoint_url,
            "headers": {"X-Org": "acme"},
        }

        yaml_text = await export_service.export_workspace()
        bundle = parse_bundle(yaml_text)

        assert "CANARY" not in yaml_text
        (setup_key,) = setup_refs(bundle.mcps[0].json_spec["endpoint_url"])
        field = bundle.setup_field(setup_key)
        assert field is not None
        assert field.type.value == "secret"
        assert bundle.mcps[0].json_spec["headers"] == {"X-Org": "acme"}

    @pytest.mark.asyncio
    async def test_a_plain_endpoint_url_is_exported_verbatim(
        self, export_service, mock_mcp_instance_service
    ):
        mock_mcp_instance_service.list.return_value = [_mcp_instance("Docs")]
        mock_mcp_instance_service.get_transport_spec_for_instance.return_value = {
            "type": "url",
            "endpoint_url": "https://mcp.example.test/mcp?format=json",
        }

        bundle = parse_bundle(await export_service.export_workspace())

        assert (
            bundle.mcps[0].json_spec["endpoint_url"] == "https://mcp.example.test/mcp?format=json"
        )
        assert bundle.setup == []
