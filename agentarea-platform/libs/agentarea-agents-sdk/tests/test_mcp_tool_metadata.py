"""What a toolset declares about its methods reaches an MCP client.

A client decides whether to ask before a call from the tool's annotations, and
an agent reads the whole docstring, not only the line an agent's own tool
schema carries.
"""

import builtins
import json
from typing import Annotated

from pydantic import BaseModel, Field

from agentarea_agents_sdk.mcp_server import create_mcp_server
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import ToolsetMetadata


class _NotesToolset(Toolset):
    # Metadata without @toolset: registering would leak into the global catalog.
    __toolset_meta__ = ToolsetMetadata(namespace="test/notes")

    @tool_method(effect="read")
    async def list(self) -> str:
        """List notes.

        Newest first.
        """
        return "[]"

    @tool_method(effect="write")
    async def create(self, text: str) -> str:
        """Create a note."""
        return text

    @tool_method(effect="destructive")
    async def delete(self, note_id: str) -> str:
        """Delete a note."""
        return note_id

    @tool_method(effect="privileged")
    async def share(self, note_id: str, user: str) -> str:
        """Share a note."""
        return note_id

    @tool_method
    async def touch(self) -> str:
        """Touch."""
        return ""


async def _tools() -> dict:
    server = create_mcp_server(toolsets=[_NotesToolset()], name="Test", workspace_argument=False)
    return {tool.name: tool for tool in await server.list_tools()}


async def test_effect_becomes_the_tool_annotations():
    tools = await _tools()

    assert tools["notes_list"].annotations.read_only_hint is True
    assert tools["notes_create"].annotations.read_only_hint is False
    assert tools["notes_create"].annotations.destructive_hint is False
    assert tools["notes_delete"].annotations.destructive_hint is True
    assert tools["notes_share"].annotations.destructive_hint is True
    assert tools["notes_touch"].annotations is None


async def test_description_is_the_whole_docstring():
    tools = await _tools()

    assert tools["notes_list"].description == "List notes.\n\nNewest first."


async def test_server_identity_reaches_initialize():
    server = create_mcp_server(
        toolsets=[],
        name="Test",
        workspace_argument=False,
        title="Test Server",
        description="Does tests.",
        version="1.2.3",
        website_url="https://example.com",
    )

    assert server.title == "Test Server"
    assert server.description == "Does tests."
    assert server.version == "1.2.3"
    assert server.website_url == "https://example.com"


class _Note(BaseModel):
    id: str
    text: str


class _TypedNotesToolset(Toolset):
    __toolset_meta__ = ToolsetMetadata(namespace="test/typed_notes")
    open_world = False

    @tool_method(
        display_name="Get note",
        effect="read",
        output=_Note,
    )
    async def get(
        self, note_id: Annotated[str, Field(description="Id of the note, from list.")]
    ) -> str:
        """Get a note."""
        return json.dumps({"id": note_id, "text": "hi"})

    @tool_method(
        display_name="List notes",
        effect="read",
        output=list[_Note],
    )
    async def list(self) -> builtins.list[dict]:
        """List notes."""
        return [{"id": "1", "text": "a"}]

    @tool_method(display_name="Sync note", effect="write", idempotent=True, open_world=True)
    async def sync(self) -> str:
        """Push a note upstream."""
        return "ok"


async def _typed() -> tuple:
    server = create_mcp_server(
        toolsets=[_TypedNotesToolset()], name="Test", workspace_argument=False
    )
    return server, {tool.name: tool for tool in await server.list_tools()}


async def test_display_name_is_the_tool_title():
    _, tools = await _typed()

    assert tools["typed_notes_get"].title == "Get note"
    assert (await _tools())["notes_list"].title is None


async def test_parameter_descriptions_reach_the_input_schema():
    _, tools = await _typed()

    schema = tools["typed_notes_get"].input_schema
    assert schema["properties"]["note_id"]["description"] == "Id of the note, from list."


async def test_declared_output_is_published_and_returned_structured():
    server, tools = await _typed()

    assert tools["typed_notes_get"].output_schema["properties"]["text"] == {
        "title": "Text",
        "type": "string",
    }
    result = await server.call_tool_result("typed_notes_get", {"note_id": "7"})
    assert result.structured_content == {"id": "7", "text": "hi"}
    assert json.loads(result.content[0].text) == {"id": "7", "text": "hi"}

    listed = await server.call_tool_result("typed_notes_list", {})
    assert listed.structured_content == {"result": [{"id": "1", "text": "a"}]}


async def test_idempotent_and_open_world_hints():
    _, tools = await _typed()

    assert tools["typed_notes_get"].annotations.open_world_hint is False
    assert tools["typed_notes_get"].annotations.idempotent_hint is None
    assert tools["typed_notes_sync"].annotations.open_world_hint is True
    assert tools["typed_notes_sync"].annotations.idempotent_hint is True
