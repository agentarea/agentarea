"""Tests for ToolConfigYAML with agent type support."""

import pytest
from agentarea_agents.schemas.import_export import ToolConfigYAML, ToolSettingsYAML
from pydantic import ValidationError


class TestToolSettingsYAMLAgentFields:
    """Tests for new agent-specific fields on ToolSettingsYAML."""

    def test_a2a_url_field(self):
        settings = ToolSettingsYAML(a2a_url="http://localhost:9000/a2a/rpc")
        assert settings.a2a_url == "http://localhost:9000/a2a/rpc"

    def test_description_override_field(self):
        settings = ToolSettingsYAML(description_override="Custom agent description")
        assert settings.description_override == "Custom agent description"

    def test_defaults_to_none(self):
        settings = ToolSettingsYAML()
        assert settings.a2a_url is None
        assert settings.description_override is None

    def test_existing_fields_still_work(self):
        settings = ToolSettingsYAML(
            disabled_methods=["delete"],
            allowed_tools=["read_file"],
        )
        assert settings.disabled_methods == ["delete"]
        assert settings.allowed_tools == ["read_file"]


class TestToolConfigYAMLAgentType:
    """Tests for ToolConfigYAML with type='agent'."""

    def test_agent_type_parses(self):
        config = ToolConfigYAML(type="agent", name="researcher")
        assert config.type == "agent"
        assert config.name == "researcher"

    def test_agent_type_with_settings(self):
        config = ToolConfigYAML(
            type="agent",
            name="researcher",
            settings=ToolSettingsYAML(
                a2a_url="http://localhost:9000/rpc",
                description_override="My custom agent",
            ),
        )
        assert config.settings is not None
        assert config.settings.a2a_url == "http://localhost:9000/rpc"
        assert config.settings.description_override == "My custom agent"

    def test_code_type_still_works(self):
        config = ToolConfigYAML(type="code", name="file_reader")
        assert config.type == "code"

    def test_mcp_type_still_works(self):
        config = ToolConfigYAML(type="mcp", name="github")
        assert config.type == "mcp"

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            ToolConfigYAML(type="invalid", name="foo")

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            ToolConfigYAML(type="agent", name="")

    def test_whitespace_name_rejected(self):
        with pytest.raises(ValidationError):
            ToolConfigYAML(type="agent", name="   ")
