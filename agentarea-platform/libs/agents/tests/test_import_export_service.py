"""SQLite-based unit tests for workspace import/export service."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import yaml

from agentarea_agents.application.import_export_service import WorkspaceImportExportService
from agentarea_agents.schemas.import_export import (
    ImportOptions,
    ImportResult,
    WorkspaceConfigYAML,
)


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
def import_export_service(
    mock_agent_service,
    mock_repository_factory,
    mock_mcp_instance_service,
    mock_provider_service,
    mock_skill_service,
):
    """Create an import/export service with mock dependencies."""
    return WorkspaceImportExportService(
        agent_service=mock_agent_service,
        repository_factory=mock_repository_factory,
        mcp_instance_service=mock_mcp_instance_service,
        provider_service=mock_provider_service,
        skill_service=mock_skill_service,
    )


class TestImportWorkspace:
    """Test workspace import functionality."""

    @pytest.mark.asyncio
    async def test_import_agent_success(self, import_export_service, mock_agent_service):
        """Test successful agent import."""
        yaml_content = """
agents:
  - name: Test Agent
    description: A test agent
    instruction: You are a test agent
    planning: false
mcp_instances: []
provider_configs: []
"""
        mock_agent_service.create_agent.return_value = MagicMock(
            id=uuid4(),
            name="Test Agent",
            description="A test agent",
        )

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is True
        assert result.created_agents == 1
        assert result.created_mcp_instances == 0
        assert result.created_provider_configs == 0
        assert len(result.errors) == 0

        mock_agent_service.create_agent.assert_called_once()
        payload = mock_agent_service.create_agent.call_args.args[0]
        assert payload.name == "Test Agent"
        assert payload.description == "A test agent"
        assert payload.instruction == "You are a test agent"
        assert payload.model_id == ""  # Empty string as per implementation
        assert payload.planning is False

    @pytest.mark.asyncio
    async def test_import_agent_with_tools(self, import_export_service, mock_agent_service):
        """Test agent import with tools configuration."""
        yaml_content = """
agents:
  - name: Agent with Tools
    description: Agent with calculator tool
    instruction: You have tools
    tools:
      - type: code
        name: agentarea/calculator
    planning: true
mcp_instances: []
provider_configs: []
"""
        mock_agent_service.create_agent.return_value = MagicMock(id=uuid4())

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is True
        assert result.created_agents == 1

        payload = mock_agent_service.create_agent.call_args.args[0]
        assert payload.tools is not None
        assert len(payload.tools) == 1
        assert payload.tools[0].type == "code"
        assert payload.tools[0].name == "agentarea/calculator"

    @pytest.mark.asyncio
    async def test_import_mcp_instance_success(
        self, import_export_service, mock_mcp_instance_service
    ):
        """Test successful MCP instance import."""
        yaml_content = """
agents: []
mcp_instances:
  - name: Test Filesystem
    description: Test file access
    server_spec_id: a1b2c3d4-e5f6-789a-bcde-123456789abc
    env_vars:
      FILESYSTEM_ROOT: /workspace
      ALLOWED_EXTENSIONS: txt,md
provider_configs: []
"""
        mock_mcp_instance_service.create_instance.return_value = MagicMock(
            id=uuid4(),
            name="Test Filesystem",
        )

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is True
        assert result.created_agents == 0
        assert result.created_mcp_instances == 1
        assert result.created_provider_configs == 0

        mock_mcp_instance_service.create_instance.assert_called_once()
        payload = mock_mcp_instance_service.create_instance.call_args.args[0]
        assert payload.name == "Test Filesystem"
        assert payload.description == "Test file access"
        assert str(payload.server_spec_id) == "a1b2c3d4-e5f6-789a-bcde-123456789abc"
        assert payload.json_spec is not None
        assert payload.json_spec["env_vars"]["FILESYSTEM_ROOT"] == "/workspace"

    @pytest.mark.asyncio
    async def test_import_provider_config_success(
        self, import_export_service, mock_provider_service
    ):
        """Test successful provider config import."""
        yaml_content = """
agents: []
mcp_instances: []
provider_configs:
  - name: Test OpenAI
    provider_spec_id: 932f3839-af2a-455e-80c6-c58fa97e312c
    api_key_placeholder: sk-test123
    endpoint_url: https://api.openai.com
"""
        mock_provider_service.create_provider_config.return_value = MagicMock(
            id=uuid4(),
            name="Test OpenAI",
        )

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is True
        assert result.created_agents == 0
        assert result.created_mcp_instances == 0
        assert result.created_provider_configs == 1

        mock_provider_service.create_provider_config.assert_called_once()
        call_kwargs = mock_provider_service.create_provider_config.call_args.kwargs
        payload = call_kwargs["payload"]
        assert payload.name == "Test OpenAI"
        assert str(payload.provider_spec_id) == "932f3839-af2a-455e-80c6-c58fa97e312c"
        assert payload.api_key == "sk-test123"
        assert payload.endpoint_url == "https://api.openai.com"

    @pytest.mark.asyncio
    async def test_import_provider_config_missing_api_key(
        self, import_export_service, mock_provider_service
    ):
        """Test provider config import fails with placeholder API key."""
        yaml_content = """
agents: []
mcp_instances: []
provider_configs:
  - name: Test OpenAI
    provider_spec_id: 932f3839-af2a-455e-80c6-c58fa97e312c
    api_key_placeholder: <REQUIRED>
"""

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is False
        assert result.created_provider_configs == 0
        assert len(result.errors) == 1
        assert "API key is required" in result.errors[0]

    @pytest.mark.asyncio
    async def test_import_full_workspace(self, import_export_service, mock_agent_service):
        """Test importing a complete workspace configuration."""
        yaml_content = """
agents:
  - name: Assistant
    description: Helpful assistant
    instruction: You are helpful
    tools:
      - type: code
        name: agentarea/calculator

mcp_instances:
  - name: Filesystem
    server_spec_id: a1b2c3d4-e5f6-789a-bcde-123456789abc
    env_vars:
      ROOT: /data

provider_configs:
  - name: OpenAI
    provider_spec_id: 932f3839-af2a-455e-80c6-c58fa97e312c
    api_key_placeholder: sk-real-key
"""
        mock_agent_service.create_agent.return_value = MagicMock(id=uuid4())

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_import_with_validation_errors(self, import_export_service):
        """Test import with YAML validation errors."""
        yaml_content = """
agents:
  - name: ""  # Empty name should fail validation
mcp_instances: []
provider_configs: []
"""

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is False
        assert len(result.errors) > 0
        assert "YAML validation error" in result.errors[0]

    @pytest.mark.asyncio
    async def test_import_with_skip_missing_dependencies(
        self, import_export_service, mock_agent_service
    ):
        """Test import with skip_missing_dependencies option."""
        yaml_content = """
agents:
  - name: Test Agent
    description: Test
mcp_instances: []
provider_configs: []
"""
        options = ImportOptions(skip_missing_dependencies=True)
        mock_agent_service.create_agent.side_effect = Exception("Creation failed")

        result = await import_export_service.import_workspace(yaml_content, options)

        assert result.success is True  # Still succeeds with skip option
        assert len(result.warnings) == 1
        assert "Failed to import agent" in result.warnings[0]


class TestExportWorkspace:
    """Test workspace export functionality."""

    @pytest.mark.asyncio
    async def test_export_agents_only(self, import_export_service, mock_agent_service):
        """Test exporting agents only."""
        mock_agent = MagicMock()
        mock_agent.workspace_id = "test-workspace"
        mock_agent.name = "Test Agent"
        mock_agent.description = "A test agent"
        mock_agent.instruction = "You are a test agent"
        mock_agent.tools = [{"type": "code", "name": "agentarea/calculator"}]
        mock_agent.planning = True
        mock_agent.a2ui_enabled = False

        mock_agent_service.list.return_value = [mock_agent]

        result = await import_export_service.export_workspace()

        # Parse the YAML output
        exported = yaml.safe_load(result)

        assert len(exported["agents"]) == 1
        assert exported["agents"][0]["name"] == "Test Agent"
        assert exported["agents"][0]["tools"] == [{"type": "code", "name": "agentarea/calculator"}]
        assert exported["agents"][0]["planning"] is True
        assert "mcp_instances" not in exported
        assert "provider_configs" not in exported

    @pytest.mark.asyncio
    async def test_export_skips_system_agents(self, import_export_service, mock_agent_service):
        """Test that system workspace agents are not exported."""
        user_agent = MagicMock()
        user_agent.workspace_id = "test-workspace"
        user_agent.name = "User Agent"
        user_agent.description = "User agent"
        user_agent.instruction = "You are a user agent"
        user_agent.tools = None
        user_agent.planning = None
        user_agent.a2ui_enabled = None

        system_agent = MagicMock()
        system_agent.workspace_id = "system"
        system_agent.name = "System Agent"
        system_agent.description = "System agent"
        system_agent.instruction = "You are a system agent"
        system_agent.tools = None
        system_agent.planning = None

        mock_agent_service.list.return_value = [user_agent, system_agent]

        result = await import_export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert len(exported["agents"]) == 1
        assert exported["agents"][0]["name"] == "User Agent"

    @pytest.mark.asyncio
    async def test_export_mcp_instances(
        self, import_export_service, mock_mcp_instance_service
    ):
        """Test exporting MCP instances."""
        mock_instance = MagicMock()
        mock_instance.workspace_id = "test-workspace"
        mock_instance.name = "Test Filesystem"
        mock_instance.description = "File access"
        mock_instance.server_spec_id = "a1b2c3d4-e5f6-789a-bcde-123456789abc"
        mock_instance.json_spec = {"env_vars": {"ROOT": "/data"}}

        mock_mcp_instance_service.list.return_value = [mock_instance]

        result = await import_export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert len(exported["mcp_instances"]) == 1
        assert exported["mcp_instances"][0]["name"] == "Test Filesystem"
        assert exported["mcp_instances"][0]["server_spec_id"] == "a1b2c3d4-e5f6-789a-bcde-123456789abc"
        assert exported["mcp_instances"][0]["env_vars"]["ROOT"] == "/data"

    @pytest.mark.asyncio
    async def test_export_provider_configs(self, import_export_service, mock_provider_service):
        """Test exporting provider configs."""
        mock_config = MagicMock()
        mock_config.workspace_id = "test-workspace"
        mock_config.name = "OpenAI Config"
        mock_config.description = "OpenAI provider"
        mock_config.provider_spec_id = UUID("932f3839-af2a-455e-80c6-c58fa97e312c")
        mock_config.endpoint_url = "https://api.openai.com"

        mock_provider_service.list_provider_configs.return_value = [mock_config]

        result = await import_export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert len(exported["provider_configs"]) == 1
        assert exported["provider_configs"][0]["name"] == "OpenAI Config"
        assert exported["provider_configs"][0]["provider_spec_id"] == "932f3839-af2a-455e-80c6-c58fa97e312c"
        assert exported["provider_configs"][0]["api_key_placeholder"] == "<REQUIRED>"
        assert exported["provider_configs"][0]["endpoint_url"] == "https://api.openai.com"

    @pytest.mark.asyncio
    async def test_export_skips_system_provider_configs(
        self, import_export_service, mock_provider_service
    ):
        """Test that system workspace provider configs are not exported."""
        user_config = MagicMock()
        user_config.workspace_id = "test-workspace"
        user_config.name = "User Config"
        user_config.description = None
        user_config.provider_spec_id = UUID("932f3839-af2a-455e-80c6-c58fa97e312c")
        user_config.endpoint_url = "https://api.openai.com"

        system_config = MagicMock()
        system_config.workspace_id = "system"
        system_config.name = "System Config"
        system_config.description = None
        system_config.provider_spec_id = UUID("932f3839-af2a-455e-80c6-c58fa97e312c")

        mock_provider_service.list_provider_configs.return_value = [user_config, system_config]

        result = await import_export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert len(exported["provider_configs"]) == 1
        assert exported["provider_configs"][0]["name"] == "User Config"


class TestImportExportRoundtrip:
    """Test import/export roundtrip scenarios."""

    @pytest.mark.asyncio
    async def test_import_export_preserves_data(
        self, import_export_service, mock_agent_service, mock_mcp_instance_service
    ):
        """Test that import followed by export preserves data."""
        original_yaml = """
agents:
  - name: Roundtrip Agent
    description: Testing roundtrip
    instruction: You are testing
    tools:
      - type: code
        name: agentarea/calculator
    planning: false
mcp_instances:
  - name: Roundtrip MCP
    server_spec_id: a1b2c3d4-e5f6-789a-bcde-123456789abc
    env_vars:
      KEY: value
provider_configs: []
"""

        # Mock created entities
        mock_agent = MagicMock()
        mock_agent.workspace_id = "test-workspace"
        mock_agent.name = "Roundtrip Agent"
        mock_agent.description = "Testing roundtrip"
        mock_agent.instruction = "You are testing"
        mock_agent.tools = [{"type": "code", "name": "agentarea/calculator"}]
        mock_agent.planning = False
        mock_agent.a2ui_enabled = False

        mock_mcp = MagicMock()
        mock_mcp.workspace_id = "test-workspace"
        mock_mcp.name = "Roundtrip MCP"
        mock_mcp.description = None
        mock_mcp.server_spec_id = "a1b2c3d4-e5f6-789a-bcde-123456789abc"
        mock_mcp.json_spec = {"env_vars": {"KEY": "value"}}

        mock_agent_service.create_agent.return_value = mock_agent
        mock_mcp_instance_service.create_instance.return_value = mock_mcp
        mock_agent_service.list.return_value = []
        mock_mcp_instance_service.list.return_value = []

        # Import
        import_result = await import_export_service.import_workspace(original_yaml)
        assert import_result.success is True

        mock_agent_service.list.return_value = [mock_agent]
        mock_mcp_instance_service.list.return_value = [mock_mcp]

        # Export
        export_result = await import_export_service.export_workspace()
        exported = yaml.safe_load(export_result)

        # Verify
        assert len(exported["agents"]) == 1
        assert exported["agents"][0]["name"] == "Roundtrip Agent"
        assert exported["agents"][0]["tools"][0]["name"] == "agentarea/calculator"
        assert len(exported["mcp_instances"]) == 1
        assert exported["mcp_instances"][0]["name"] == "Roundtrip MCP"


class TestValidation:
    """Test validation during import."""

    @pytest.mark.asyncio
    async def test_validate_code_tools(self, import_export_service):
        """Test validation of code tools."""
        yaml_content = """
agents:
  - name: Agent with Invalid Tool
    tools:
      - type: code
        name: invalid/tool
mcp_instances: []
provider_configs: []
"""
        with patch(
            "agentarea_agents_sdk.tools.code_tools_loader.get_code_tools_metadata",
            return_value={"agentarea/calculator": {}},
        ):
            result = await import_export_service.import_workspace(yaml_content)

        assert result.success is False
        assert len(result.errors) > 0
        assert "Unknown code tool" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_mcp_server_specs(
        self, import_export_service, mock_repository_factory
    ):
        """Test validation of MCP server specs."""
        yaml_content = """
agents: []
mcp_instances:
  - name: Invalid MCP
    server_spec_id: invalid-spec-id
provider_configs: []
"""
        mock_repo = MagicMock()
        mock_repo.list_all = AsyncMock(return_value=[])
        mock_repository_factory.create_repository.return_value = mock_repo

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is False
        assert len(result.errors) > 0
        assert "Unknown server spec" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_provider_specs(
        self, import_export_service, mock_provider_service
    ):
        """Test validation of provider specs."""
        yaml_content = """
agents: []
mcp_instances: []
provider_configs:
  - name: Invalid Provider
    provider_spec_id: invalid-spec-id
    api_key_placeholder: sk-key
"""
        mock_provider_service.list_provider_specs.return_value = []

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is False
        assert len(result.errors) > 0
        assert "Unknown provider spec" in result.errors[0]


class TestOverrideExisting:
    """Test override_existing option."""

    @pytest.mark.asyncio
    async def test_override_existing_agent(
        self, import_export_service, mock_agent_service
    ):
        """Test updating existing agent with override flag."""
        yaml_content = """
agents:
  - name: Existing Agent
    description: Updated description
mcp_instances: []
provider_configs: []
"""
        existing_agent = MagicMock()
        existing_agent.id = uuid4()
        existing_agent.name = "Existing Agent"

        mock_agent_service.list.return_value = [existing_agent]
        mock_agent_service.update_agent.return_value = MagicMock(id=existing_agent.id)

        options = ImportOptions(override_existing=True)
        result = await import_export_service.import_workspace(yaml_content, options)

        assert result.success is True
        mock_agent_service.update_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_override_existing_agent(
        self, import_export_service, mock_agent_service
    ):
        """Test that existing agent without override flag raises error."""
        yaml_content = """
agents:
  - name: Existing Agent
    description: Updated description
mcp_instances: []
provider_configs: []
"""
        existing_agent = MagicMock()
        existing_agent.name = "Existing Agent"

        mock_agent_service.list.return_value = [existing_agent]

        options = ImportOptions(override_existing=False)
        result = await import_export_service.import_workspace(yaml_content, options)

        assert result.success is False
        assert len(result.errors) == 1
        assert "already exists" in result.errors[0]


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_workspace_import(self, import_export_service):
        """Test importing empty workspace."""
        yaml_content = """
agents: []
mcp_instances: []
provider_configs: []
"""
        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is True
        assert result.created_agents == 0
        assert result.created_mcp_instances == 0
        assert result.created_provider_configs == 0

    @pytest.mark.asyncio
    async def test_invalid_yaml(self, import_export_service):
        """Test handling of invalid YAML."""
        yaml_content = "invalid: yaml: content: ["

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is False
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_export_no_services(self, import_export_service):
        """Test export when MCP and provider services are None."""
        service = WorkspaceImportExportService(
            agent_service=import_export_service.agent_service,
            repository_factory=import_export_service.repository_factory,
            mcp_instance_service=None,
            provider_service=None,
        )

        import_export_service.agent_service.list.return_value = []

        result = await service.export_workspace()
        exported = yaml.safe_load(result)

        # With no services, these sections may be missing or empty
        assert exported.get("mcp_instances", []) == []
        assert exported.get("provider_configs", []) == []


class TestSkillImportExport:
    """Test skill import/export functionality."""

    @pytest.mark.asyncio
    async def test_import_skill_from_content(
        self, import_export_service, mock_skill_service
    ):
        """Test importing a skill from inline content."""
        yaml_content = """
skills:
  - name: Test Skill
    description: A test skill
    content: |
      ---
      name: Test Skill
      description: A test skill
      ---
      # Test Skill
      This is a test skill.
agents: []
mcp_instances: []
provider_configs: []
"""
        mock_skill = MagicMock()
        mock_skill.id = uuid4()
        mock_skill.name = "Test Skill"
        mock_skill_service.create_from_content.return_value = mock_skill

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is True
        assert result.created_skills == 1
        mock_skill_service.create_from_content.assert_called_once()
        # Service now takes a SkillCreateFromContent payload as a positional arg.
        (call_payload,) = mock_skill_service.create_from_content.call_args.args
        assert call_payload.name == "Test Skill"
        assert call_payload.description == "A test skill"

    @pytest.mark.asyncio
    async def test_import_skill_from_github(
        self, import_export_service, mock_skill_service
    ):
        """Test importing a skill from GitHub."""
        yaml_content = """
skills:
  - name: GitHub Skill
    github: https://github.com/owner/skill-repo
agents: []
mcp_instances: []
provider_configs: []
"""
        mock_skill = MagicMock()
        mock_skill.id = uuid4()
        mock_skill.name = "GitHub Skill"
        mock_skill_service.create_from_github.return_value = mock_skill

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is True
        assert result.created_skills == 1
        mock_skill_service.create_from_github.assert_called_once()
        # Service now takes a SkillImportFromGithub payload as a positional arg.
        (call_payload,) = mock_skill_service.create_from_github.call_args.args
        assert call_payload.github_url == "https://github.com/owner/skill-repo"
        assert call_payload.name == "GitHub Skill"

    @pytest.mark.asyncio
    async def test_import_skill_from_path(
        self, import_export_service, mock_skill_service
    ):
        """Test importing a skill from local path."""
        yaml_content = """
skills:
  - name: Local Skill
    path: ./skills/my-skill
agents: []
mcp_instances: []
provider_configs: []
"""
        mock_skill = MagicMock()
        mock_skill.id = uuid4()
        mock_skill.name = "Local Skill"
        mock_skill_service.create_from_path.return_value = mock_skill

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is True
        assert result.created_skills == 1
        mock_skill_service.create_from_path.assert_called_once()
        call_kwargs = mock_skill_service.create_from_path.call_args.kwargs
        assert call_kwargs["path"] == "./skills/my-skill"
        assert call_kwargs["name"] == "Local Skill"

    @pytest.mark.asyncio
    async def test_import_agent_with_skill_names(
        self, import_export_service, mock_agent_service, mock_skill_service
    ):
        """Test importing an agent that references skills by name."""
        yaml_content = """
skills:
  - name: Helper Skill
    content: |
      # Helper Skill
      Helps with stuff
agents:
  - name: Agent with Skills
    description: An agent with skills
    skill_names:
      - Helper Skill
mcp_instances: []
provider_configs: []
"""
        skill_id = uuid4()
        mock_skill = MagicMock()
        mock_skill.id = skill_id
        mock_skill.name = "Helper Skill"
        mock_skill_service.create_from_content.return_value = mock_skill

        mock_agent = MagicMock()
        mock_agent.id = uuid4()
        mock_agent.name = "Agent with Skills"
        mock_agent_service.create_agent.return_value = mock_agent

        result = await import_export_service.import_workspace(yaml_content)

        assert result.success is True
        assert result.created_skills == 1
        assert result.created_agents == 1

        # Verify agent was created with skill_ids
        payload = mock_agent_service.create_agent.call_args.args[0]
        assert payload.skill_ids is not None
        assert skill_id in payload.skill_ids

    @pytest.mark.asyncio
    async def test_import_agent_with_unknown_skill_fails(
        self, import_export_service, mock_agent_service, mock_skill_service
    ):
        """Test that importing an agent with unknown skill reference fails."""
        yaml_content = """
skills: []
agents:
  - name: Agent with Bad Skill
    description: An agent with bad skill reference
    skill_names:
      - Non Existent Skill
mcp_instances: []
provider_configs: []
"""
        result = await import_export_service.import_workspace(yaml_content)

        # Should fail validation due to unknown skill reference
        assert result.success is False
        assert len(result.errors) > 0
        assert "unknown skill" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_import_agent_with_unknown_skill_skipped(
        self, import_export_service, mock_agent_service, mock_skill_service
    ):
        """Test that unknown skill reference can be skipped with option."""
        yaml_content = """
skills: []
agents:
  - name: Agent with Bad Skill
    description: An agent with bad skill reference
    skill_names:
      - Non Existent Skill
mcp_instances: []
provider_configs: []
"""
        mock_agent = MagicMock()
        mock_agent.id = uuid4()
        mock_agent.name = "Agent with Bad Skill"
        mock_agent_service.create_agent.return_value = mock_agent

        options = ImportOptions(skip_missing_dependencies=True)
        result = await import_export_service.import_workspace(yaml_content, options)

        assert result.success is True
        assert result.created_agents == 1
        # Should have warning about unknown skill
        assert len(result.warnings) >= 1

    @pytest.mark.asyncio
    async def test_export_skills(self, import_export_service, mock_skill_service):
        """Test exporting skills."""
        mock_skill = MagicMock()
        mock_skill.workspace_id = "test-workspace"
        mock_skill.id = uuid4()
        mock_skill.name = "Export Skill"
        mock_skill.description = "A skill to export"
        mock_skill.content = "# Export Skill\nContent here"
        mock_skill.source_url = None

        mock_skill_service.list.return_value = [mock_skill]

        result = await import_export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert "skills" in exported
        assert len(exported["skills"]) == 1
        assert exported["skills"][0]["name"] == "Export Skill"
        assert exported["skills"][0]["description"] == "A skill to export"
        assert exported["skills"][0]["content"] == "# Export Skill\nContent here"

    @pytest.mark.asyncio
    async def test_export_github_skill(self, import_export_service, mock_skill_service):
        """Test exporting a skill that was imported from GitHub."""
        mock_skill = MagicMock()
        mock_skill.workspace_id = "test-workspace"
        mock_skill.id = uuid4()
        mock_skill.name = "GitHub Skill"
        mock_skill.description = "From GitHub"
        mock_skill.content = "# Skill content"
        mock_skill.source_url = "https://github.com/owner/repo"

        mock_skill_service.list.return_value = [mock_skill]

        result = await import_export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert "skills" in exported
        assert len(exported["skills"]) == 1
        assert exported["skills"][0]["name"] == "GitHub Skill"
        assert exported["skills"][0]["github"] == "https://github.com/owner/repo"
        # Should not include content for GitHub-sourced skills
        assert "content" not in exported["skills"][0]

    @pytest.mark.asyncio
    async def test_export_agent_with_skills(
        self, import_export_service, mock_agent_service, mock_skill_service
    ):
        """Test exporting an agent that has skills attached."""
        skill_id = uuid4()
        mock_skill = MagicMock()
        mock_skill.id = skill_id
        mock_skill.name = "Attached Skill"
        mock_skill.description = "Attached to agent"
        mock_skill.content = "# Content"
        mock_skill.source_url = None
        mock_skill.workspace_id = "test-workspace"

        mock_agent = MagicMock()
        mock_agent.workspace_id = "test-workspace"
        mock_agent.name = "Agent with Skill"
        mock_agent.description = "Has skills"
        mock_agent.instruction = "Instructions"
        mock_agent.tools = None
        mock_agent.planning = None
        mock_agent.a2ui_enabled = None
        mock_agent.skills = [mock_skill]

        mock_skill_service.list.return_value = [mock_skill]
        mock_agent_service.list.return_value = [mock_agent]

        result = await import_export_service.export_workspace()
        exported = yaml.safe_load(result)

        assert "agents" in exported
        assert len(exported["agents"]) == 1
        assert "skill_names" in exported["agents"][0]
        assert exported["agents"][0]["skill_names"] == ["Attached Skill"]

    @pytest.mark.asyncio
    async def test_skill_import_export_roundtrip(
        self, import_export_service, mock_agent_service, mock_skill_service
    ):
        """Test full roundtrip of skills import then export."""
        original_yaml = """
skills:
  - name: Roundtrip Skill
    description: For testing roundtrip
    content: |
      # Roundtrip Skill
      Test content
agents:
  - name: Roundtrip Agent
    description: Agent with skill
    skill_names:
      - Roundtrip Skill
mcp_instances: []
provider_configs: []
"""
        skill_id = uuid4()
        mock_skill = MagicMock()
        mock_skill.workspace_id = "test-workspace"
        mock_skill.id = skill_id
        mock_skill.name = "Roundtrip Skill"
        mock_skill.description = "For testing roundtrip"
        mock_skill.content = "# Roundtrip Skill\nTest content"
        mock_skill.source_url = None

        mock_agent = MagicMock()
        mock_agent.workspace_id = "test-workspace"
        mock_agent.name = "Roundtrip Agent"
        mock_agent.description = "Agent with skill"
        mock_agent.instruction = ""
        mock_agent.tools = None
        mock_agent.planning = None
        mock_agent.a2ui_enabled = None
        mock_agent.skills = [mock_skill]

        mock_skill_service.create_from_content.return_value = mock_skill
        mock_agent_service.create_agent.return_value = mock_agent
        # Note: list() returns [] by default from fixture, set populated list only for export

        # Import
        import_result = await import_export_service.import_workspace(original_yaml)
        assert import_result.success is True
        assert import_result.created_skills == 1
        assert import_result.created_agents == 1

        # Set up list results for export phase
        mock_skill_service.list.return_value = [mock_skill]
        mock_agent_service.list.return_value = [mock_agent]

        # Export
        export_result = await import_export_service.export_workspace()
        exported = yaml.safe_load(export_result)

        # Verify roundtrip
        assert len(exported["skills"]) == 1
        assert exported["skills"][0]["name"] == "Roundtrip Skill"
        assert len(exported["agents"]) == 1
        assert exported["agents"][0]["skill_names"] == ["Roundtrip Skill"]
