"""Tests for the tool-config discriminated union and its per-type settings."""

import pytest
from agentarea_agents.schemas.import_export import (
    TOOL_CONFIG_ADAPTER,
    AgentToolConfig,
    AgentToolSettings,
    CodeToolConfig,
    McpToolConfig,
    McpToolSettings,
)
from pydantic import ValidationError


class TestAgentToolSettings:
    """Agent-specific settings live only on the agent variant."""

    def test_a2a_url_field(self):
        settings = AgentToolSettings(a2a_url="http://localhost:9000/a2a/rpc")
        assert settings.a2a_url == "http://localhost:9000/a2a/rpc"

    def test_description_override_field(self):
        settings = AgentToolSettings(description_override="Custom agent description")
        assert settings.description_override == "Custom agent description"

    def test_defaults_to_none(self):
        settings = AgentToolSettings()
        assert settings.a2a_url is None
        assert settings.description_override is None


class TestMcpToolSettings:
    """allowed_tools is now typed permission objects (was the list[Any] FIXME)."""

    def test_allowed_tools_coerces_plain_strings(self):
        settings = McpToolSettings(allowed_tools=["read_file"])
        assert settings.allowed_tools is not None
        assert settings.allowed_tools[0].tool_name == "read_file"
        assert settings.allowed_tools[0].requires_user_confirmation is False

    def test_allowed_tools_accepts_permission_objects(self):
        settings = McpToolSettings(
            allowed_tools=[{"tool_name": "delete", "requires_user_confirmation": True}]
        )
        assert settings.allowed_tools is not None
        assert settings.allowed_tools[0].requires_user_confirmation is True


class TestToolConfigDiscrimination:
    """The discriminated union selects the right variant by ``type``."""

    def test_agent_variant(self):
        config = AgentToolConfig(name="researcher")
        assert config.type == "agent"
        assert config.name == "researcher"

    def test_agent_variant_with_settings(self):
        config = AgentToolConfig(
            name="researcher",
            settings=AgentToolSettings(
                a2a_url="http://localhost:9000/rpc",
                description_override="My custom agent",
            ),
        )
        assert config.settings is not None
        assert config.settings.a2a_url == "http://localhost:9000/rpc"
        assert config.settings.description_override == "My custom agent"

    def test_code_variant(self):
        assert CodeToolConfig(name="file_reader").type == "code"

    def test_mcp_variant(self):
        assert McpToolConfig(name="github").type == "mcp"

    def test_adapter_selects_variant_by_type(self):
        cfg = TOOL_CONFIG_ADAPTER.validate_python({"type": "agent", "name": "researcher"})
        assert isinstance(cfg, AgentToolConfig)

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            TOOL_CONFIG_ADAPTER.validate_python({"type": "invalid", "name": "foo"})

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            AgentToolConfig(name="")

    def test_whitespace_name_rejected(self):
        with pytest.raises(ValidationError):
            AgentToolConfig(name="   ")

    def test_agent_only_field_unrepresentable_on_code_tool(self):
        """DDD win: a2a_url is dropped on a code tool, not silently carried."""
        cfg = TOOL_CONFIG_ADAPTER.validate_python(
            {"type": "code", "name": "x", "settings": {"a2a_url": "http://nope"}}
        )
        assert isinstance(cfg, CodeToolConfig)
        assert cfg.settings is not None
        assert not hasattr(cfg.settings, "a2a_url")
