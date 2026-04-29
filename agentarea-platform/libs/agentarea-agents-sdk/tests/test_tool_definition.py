"""Tests for ToolDefinition + Pydantic-aware schema generation."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel

from agentarea_agents_sdk.tools import (
    ToolDefinition,
    Toolset,
    ToolsetMetadata,
    build_method_schema,
    build_tool_definition,
    tool_method,
    toolset,
)


class AgentCreatePayload(BaseModel):
    """Pydantic stand-in for AgentCreate used in tests."""

    name: str
    description: str = ""
    instruction: str = ""
    model_id: str
    agent_type: Literal["stateless", "stateful"] = "stateless"


class AgentSummary(BaseModel):
    id: str
    name: str


@toolset(
    namespace="agentarea/agents",
    display_name="Agent Management",
    description="Create, list, update, delete agents.",
    category="platform",
    register=False,
)
class _AgentsTestToolset(Toolset):
    """Test toolset mirroring the AgentsToolset surface."""

    @tool_method
    async def list(self, limit: int = 50, offset: int = 0) -> str:
        """List all agents."""
        return "[]"

    @tool_method(display_name="Create Agent")
    async def create(self, payload: AgentCreatePayload) -> AgentSummary:
        """Create a new agent."""
        return AgentSummary(id="x", name=payload.name)

    @tool_method
    async def update(
        self,
        agent_id: str,
        name: str = "",
        description: str = "",
    ) -> str:
        """Update an agent."""
        return "{}"


class TestToolsetMetadata:
    def test_class_decorator_stamps_metadata(self):
        meta = _AgentsTestToolset.__toolset_meta__
        assert isinstance(meta, ToolsetMetadata)
        assert meta.namespace == "agentarea/agents"
        assert meta.display_name == "Agent Management"
        assert meta.category == "platform"

    def test_instance_metadata_property(self):
        ts = _AgentsTestToolset()
        assert ts.metadata is not None
        assert ts.metadata.namespace == "agentarea/agents"

    def test_description_falls_back_to_metadata(self):
        ts = _AgentsTestToolset()
        # metadata.description set via @toolset takes precedence over class docstring
        assert ts.description == "Create, list, update, delete agents."


class TestToolMethodMetadata:
    def test_default_display_name_from_method(self):
        ts = _AgentsTestToolset()
        list_method = ts._tool_methods["list"]
        assert list_method._tool_meta.display_name == "List"
        assert list_method._tool_meta.description == "List all agents."

    def test_explicit_display_name(self):
        ts = _AgentsTestToolset()
        create_method = ts._tool_methods["create"]
        assert create_method._tool_meta.display_name == "Create Agent"


class TestSchemaGeneration:
    def test_single_basemodel_param_flattens(self):
        """A single BaseModel param → tool schema IS the model's schema."""
        ts = _AgentsTestToolset()
        schema = build_method_schema(ts._tool_methods["create"])

        # Should be the AgentCreatePayload schema directly, not wrapped in {payload: ...}
        assert "payload" not in schema.get("properties", {})
        assert "name" in schema["properties"]
        assert "model_id" in schema["properties"]
        assert "agent_type" in schema["properties"]
        assert set(schema["required"]) == {"name", "model_id"}

    def test_primitive_params_build_object_schema(self):
        ts = _AgentsTestToolset()
        schema = build_method_schema(ts._tool_methods["update"])

        props = schema["properties"]
        assert props["agent_id"]["type"] == "string"
        assert props["name"]["type"] == "string"
        assert props["description"]["type"] == "string"
        # only agent_id is required (others have defaults)
        assert schema["required"] == ["agent_id"]

    def test_int_with_default(self):
        ts = _AgentsTestToolset()
        schema = build_method_schema(ts._tool_methods["list"])

        assert schema["properties"]["limit"]["type"] == "integer"
        assert schema["properties"]["limit"]["default"] == 50
        assert schema.get("required", []) == []

    def test_literal_type_renders_as_enum(self):
        ts = _AgentsTestToolset()
        schema = build_method_schema(ts._tool_methods["create"])

        agent_type_schema = schema["properties"]["agent_type"]
        # Pydantic renders Literal[...] as enum
        assert agent_type_schema.get("enum") == ["stateless", "stateful"]


class TestToolDefinition:
    def test_get_tool_definitions_per_method(self):
        ts = _AgentsTestToolset()
        defs = ts.get_tool_definitions()

        assert len(defs) == 3
        names = {d.name for d in defs}
        assert names == {
            f"{ts.name}_list",
            f"{ts.name}_create",
            f"{ts.name}_update",
        }
        for d in defs:
            assert isinstance(d, ToolDefinition)
            assert d.description
            assert "type" in d.parameters_json_schema

    def test_to_mcp_shape(self):
        td = build_tool_definition(
            tool_name="agents_create",
            method=_AgentsTestToolset.create,
        )
        mcp = td.to_mcp()
        assert mcp == {
            "name": "agents_create",
            "description": td.description,
            "inputSchema": td.parameters_json_schema,
        }

    def test_to_openai_shape(self):
        td = build_tool_definition(
            tool_name="agents_create",
            method=_AgentsTestToolset.create,
        )
        oa = td.to_openai()
        assert oa["type"] == "function"
        assert oa["function"]["name"] == "agents_create"
        assert oa["function"]["parameters"] == td.parameters_json_schema

    def test_custom_name_prefix(self):
        ts = _AgentsTestToolset()
        defs = ts.get_tool_definitions(name_prefix="platform_agents")
        names = {d.name for d in defs}
        assert names == {
            "platform_agents_list",
            "platform_agents_create",
            "platform_agents_update",
        }


class TestBackwardCompat:
    """Existing toolsets without @toolset / Pydantic params keep working."""

    def test_toolset_without_decorator_has_no_metadata(self):
        class Plain(Toolset):
            """Plain toolset."""

            @tool_method
            async def echo(self, text: str) -> str:
                """Echo."""
                return text

        ts = Plain()
        assert ts.metadata is None
        assert ts.description == "Plain toolset."

    @pytest.mark.asyncio
    async def test_execute_still_works(self):
        class Plain(Toolset):
            @tool_method
            async def echo(self, text: str) -> str:
                """Echo."""
                return text

            @tool_method
            async def shout(self, text: str) -> str:
                """Shout."""
                return text.upper()

        ts = Plain()
        result = await ts.execute(action="echo", text="hi")
        assert result["success"] is True
        assert result["result"] == "hi"

    def test_old_get_schema_still_returns_dict(self):
        ts = _AgentsTestToolset()
        schema = ts.get_schema()
        assert "parameters" in schema
        assert "properties" in schema["parameters"]
