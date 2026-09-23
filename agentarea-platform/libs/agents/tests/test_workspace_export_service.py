"""Unit tests for the workspace export service."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import yaml
from agentarea_agents.application.workspace_export_service import WorkspaceExportService
from agentarea_agents.schemas.import_export import WorkspaceConfigYAML


@pytest.fixture
def mock_agent_service():
    """Create a mock agent service."""
    service = MagicMock()
    service.list = AsyncMock(return_value=[])
    service.get_by_name = AsyncMock(return_value=None)
    service.create_agent = AsyncMock()
    service.update_agent = AsyncMock()
    # get_with_skills is called during export to eager-load skills relationship
    service.get_with_skills = AsyncMock(side_effect=lambda agent_id: None)
    return service


@pytest.fixture
def mock_repository_factory():
    """Create a mock repository factory."""
    factory = MagicMock()
    mock_repo = MagicMock()
    mock_repo.list_all = AsyncMock(
        return_value=[MagicMock(id=UUID("a1b2c3d4-e5f6-789a-bcde-123456789abc"))]
    )
    factory.create_repository = MagicMock(return_value=mock_repo)
    return factory


@pytest.fixture
def mock_mcp_instance_service():
    """Create a mock MCP instance service."""
    service = MagicMock()
    service.list = AsyncMock(return_value=[])
    service.create_instance = AsyncMock()
    service.update_instance = AsyncMock()
    return service


@pytest.fixture
def mock_provider_service():
    """Create a mock provider service."""
    service = MagicMock()
    service.list_provider_configs = AsyncMock(return_value=[])
    service.list_provider_specs = AsyncMock(
        return_value=[MagicMock(id=UUID("932f3839-af2a-455e-80c6-c58fa97e312c"))]
    )
    service.create_provider_config = AsyncMock()
    service.update_provider_config = AsyncMock()
    return service


@pytest.fixture
def mock_skill_service():
    """Create a mock skill service."""
    service = MagicMock()
    service.list = AsyncMock(return_value=[])
    service.get_by_name = AsyncMock(return_value=None)
    service.create_from_content = AsyncMock()
    service.create_from_github = AsyncMock()
    service.create_from_path = AsyncMock()
    service.delete = AsyncMock()
    return service


@pytest.fixture
def export_service(
    mock_agent_service,
    mock_repository_factory,
    mock_mcp_instance_service,
    mock_provider_service,
    mock_skill_service,
):
    """Create an import/export service with mock dependencies."""
    return WorkspaceExportService(
        agent_service=mock_agent_service,
        repository_factory=mock_repository_factory,
        mcp_instance_service=mock_mcp_instance_service,
        provider_service=mock_provider_service,
        skill_service=mock_skill_service,
    )


class TestExportWorkspace:
    """Test workspace export functionality."""

    @pytest.mark.asyncio
    async def test_export_agents_only(self, export_service, mock_agent_service):
        """Test exporting agents only."""
        mock_agent = MagicMock()
        mock_agent.workspace_id = "test-workspace"
        mock_agent.registry_item_id = None
        mock_agent.is_catalog = False
        mock_agent.name = "Test Agent"
        mock_agent.description = "A test agent"
        mock_agent.instruction = "You are a test agent"
        mock_agent.tools = [{"type": "code", "name": "agentarea/math"}]
        mock_agent.planning = True
        mock_agent.a2ui_enabled = False

        mock_agent_service.list.return_value = [mock_agent]

        result = await export_service.export_workspace()

        # Parse the YAML output
        exported = yaml.safe_load(result)

        assert len(exported["agents"]) == 1
        assert exported["agents"][0]["name"] == "Test Agent"
        assert exported["agents"][0]["tools"] == [{"type": "code", "name": "agentarea/math"}]
        assert exported["agents"][0]["planning"] is True
        assert "mcp_instances" not in exported
        assert "provider_configs" not in exported

    @pytest.mark.asyncio
    async def test_export_skips_catalog_agents(self, export_service, mock_agent_service):
        """Test that catalog-projection (built-in) agents are not exported."""
        user_agent = MagicMock()
        user_agent.workspace_id = "test-workspace"
        user_agent.registry_item_id = None
        user_agent.is_catalog = False
        user_agent.name = "User Agent"
        user_agent.description = "User agent"
        user_agent.instruction = "You are a user agent"
        user_agent.tools = None
        user_agent.planning = None
        user_agent.a2ui_enabled = None

        # Built-in: a read-only catalog projection (is_catalog True, not persisted).
        catalog_agent = MagicMock()
        catalog_agent.workspace_id = "platform"
        catalog_agent.registry_item_id = "ri-catalog-agent"
        catalog_agent.is_catalog = True
        catalog_agent.name = "Catalog Agent"
        catalog_agent.description = "Catalog agent"
        catalog_agent.instruction = "You are a catalog agent"
        catalog_agent.tools = None
        catalog_agent.planning = None

        mock_agent_service.list.return_value = [user_agent, catalog_agent]

        result = await export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert len(exported["agents"]) == 1
        assert exported["agents"][0]["name"] == "User Agent"

    @pytest.mark.asyncio
    async def test_export_includes_forked_agents(self, export_service, mock_agent_service):
        """A forked agent carries registry_item_id but is owned content -> exported."""
        forked_agent = MagicMock()
        forked_agent.workspace_id = "test-workspace"
        forked_agent.registry_item_id = "ri-forked-from"
        forked_agent.is_catalog = False
        forked_agent.name = "Forked Agent"
        forked_agent.description = "A fork of a catalog agent"
        forked_agent.instruction = "You are a forked agent"
        forked_agent.tools = None
        forked_agent.planning = None
        forked_agent.a2ui_enabled = None

        mock_agent_service.list.return_value = [forked_agent]

        result = await export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert len(exported["agents"]) == 1
        assert exported["agents"][0]["name"] == "Forked Agent"

    @pytest.mark.asyncio
    async def test_export_mcp_instances(self, export_service, mock_mcp_instance_service):
        """Test exporting MCP instances."""
        mock_instance = MagicMock()
        mock_instance.workspace_id = "test-workspace"
        mock_instance.registry_item_id = None
        mock_instance.is_catalog = False
        mock_instance.name = "Test Filesystem"
        mock_instance.description = "File access"
        mock_instance.server_spec_id = "a1b2c3d4-e5f6-789a-bcde-123456789abc"
        # json_spec stores the secret *names*; the values live in the secret manager.
        mock_instance.json_spec = {"env_vars": ["ROOT", "TOKEN"]}
        mock_instance.get_configured_env_vars.return_value = ["ROOT", "TOKEN"]

        mock_mcp_instance_service.list.return_value = [mock_instance]

        result = await export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert len(exported["mcp_instances"]) == 1
        assert exported["mcp_instances"][0]["name"] == "Test Filesystem"
        assert (
            exported["mcp_instances"][0]["server_spec_id"] == "a1b2c3d4-e5f6-789a-bcde-123456789abc"
        )
        # Secrets export as placeholders, and the result must satisfy the import
        # schema -- emitting the raw name list here made exports unimportable.
        assert exported["mcp_instances"][0]["env_vars"] == {
            "ROOT": "<REQUIRED>",
            "TOKEN": "<REQUIRED>",
        }
        WorkspaceConfigYAML(**exported)

    @pytest.mark.asyncio
    async def test_export_provider_configs(self, export_service, mock_provider_service):
        """Test exporting provider configs."""
        mock_config = MagicMock()
        mock_config.workspace_id = "test-workspace"
        mock_config.registry_item_id = None
        mock_config.is_catalog = False
        mock_config.name = "OpenAI Config"
        mock_config.description = "OpenAI provider"
        mock_config.provider_spec_id = UUID("932f3839-af2a-455e-80c6-c58fa97e312c")
        mock_config.endpoint_url = "https://api.openai.com"

        mock_provider_service.list_provider_configs.return_value = [mock_config]

        result = await export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert len(exported["provider_configs"]) == 1
        assert exported["provider_configs"][0]["name"] == "OpenAI Config"
        assert (
            exported["provider_configs"][0]["provider_spec_id"]
            == "932f3839-af2a-455e-80c6-c58fa97e312c"
        )
        assert exported["provider_configs"][0]["api_key_placeholder"] == "<REQUIRED>"
        assert exported["provider_configs"][0]["endpoint_url"] == "https://api.openai.com"

    @pytest.mark.asyncio
    async def test_export_includes_all_provider_configs(
        self, export_service, mock_provider_service
    ):
        """Provider configs are never catalog projections, so all are exported.

        After the registry-catalog refactor there are no persisted built-in
        provider configs; a config carrying a registry_item_id is still owned,
        exportable content (not a catalog projection).
        """
        user_config = MagicMock()
        user_config.workspace_id = "test-workspace"
        user_config.registry_item_id = None
        user_config.is_catalog = False
        user_config.name = "User Config"
        user_config.description = None
        user_config.provider_spec_id = UUID("932f3839-af2a-455e-80c6-c58fa97e312c")
        user_config.endpoint_url = "https://api.openai.com"

        # Carries a registry_item_id link but is owned content, not a projection.
        linked_config = MagicMock()
        linked_config.workspace_id = "test-workspace"
        linked_config.registry_item_id = "ri-linked-config"
        linked_config.is_catalog = False
        linked_config.name = "Linked Config"
        linked_config.description = None
        linked_config.provider_spec_id = UUID("932f3839-af2a-455e-80c6-c58fa97e312c")
        linked_config.endpoint_url = "https://api.openai.com"

        mock_provider_service.list_provider_configs.return_value = [user_config, linked_config]

        result = await export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert len(exported["provider_configs"]) == 2
        names = {c["name"] for c in exported["provider_configs"]}
        assert names == {"User Config", "Linked Config"}

    @pytest.mark.asyncio
    async def test_export_no_services(self, export_service):
        """Test export when MCP and provider services are None."""
        service = WorkspaceExportService(
            agent_service=export_service.agent_service,
            repository_factory=export_service.repository_factory,
            mcp_instance_service=None,
            provider_service=None,
        )

        export_service.agent_service.list.return_value = []

        result = await service.export_workspace()
        exported = yaml.safe_load(result)

        # With no services, these sections may be missing or empty
        assert exported.get("mcp_instances", []) == []
        assert exported.get("provider_configs", []) == []


class TestSkillExport:
    """Skill export behaviour."""

    @pytest.mark.asyncio
    async def test_export_skills(self, export_service, mock_skill_service):
        """Test exporting skills."""
        mock_skill = MagicMock()
        mock_skill.workspace_id = "test-workspace"
        mock_skill.registry_item_id = None
        mock_skill.is_catalog = False
        mock_skill.id = uuid4()
        mock_skill.name = "Export Skill"
        mock_skill.description = "A skill to export"
        mock_skill.content = "# Export Skill\nContent here"
        mock_skill.source_url = None

        mock_skill_service.list.return_value = [mock_skill]

        result = await export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert "skills" in exported
        assert len(exported["skills"]) == 1
        assert exported["skills"][0]["name"] == "Export Skill"
        assert exported["skills"][0]["description"] == "A skill to export"
        assert exported["skills"][0]["content"] == "# Export Skill\nContent here"

    @pytest.mark.asyncio
    async def test_export_github_skill(self, export_service, mock_skill_service):
        """Test exporting a skill that was imported from GitHub."""
        mock_skill = MagicMock()
        mock_skill.workspace_id = "test-workspace"
        mock_skill.registry_item_id = None
        mock_skill.is_catalog = False
        mock_skill.id = uuid4()
        mock_skill.name = "GitHub Skill"
        mock_skill.description = "From GitHub"
        mock_skill.content = "# Skill content"
        mock_skill.source_url = "https://github.com/owner/repo"

        mock_skill_service.list.return_value = [mock_skill]

        result = await export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert "skills" in exported
        assert len(exported["skills"]) == 1
        assert exported["skills"][0]["name"] == "GitHub Skill"
        assert exported["skills"][0]["github"] == "https://github.com/owner/repo"
        # Should not include content for GitHub-sourced skills
        assert "content" not in exported["skills"][0]

    @pytest.mark.asyncio
    async def test_export_agent_with_skills(
        self, export_service, mock_agent_service, mock_skill_service
    ):
        """Test exporting an agent that has skills attached."""
        skill_id = uuid4()
        mock_skill = MagicMock()
        mock_skill.id = skill_id
        mock_skill.registry_item_id = None
        mock_skill.is_catalog = False
        mock_skill.name = "Attached Skill"
        mock_skill.description = "Attached to agent"
        mock_skill.content = "# Content"
        mock_skill.source_url = None
        mock_skill.workspace_id = "test-workspace"

        mock_agent = MagicMock()
        mock_agent.workspace_id = "test-workspace"
        mock_agent.registry_item_id = None
        mock_agent.is_catalog = False
        mock_agent.name = "Agent with Skill"
        mock_agent.description = "Has skills"
        mock_agent.instruction = "Instructions"
        mock_agent.tools = None
        mock_agent.planning = None
        mock_agent.a2ui_enabled = None
        mock_agent.skills = [mock_skill]

        mock_skill_service.list.return_value = [mock_skill]
        mock_agent_service.list.return_value = [mock_agent]

        result = await export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert "agents" in exported
        assert len(exported["agents"]) == 1
        assert "skill_names" in exported["agents"][0]
        assert exported["agents"][0]["skill_names"] == ["Attached Skill"]
