"""A code tool that could not do the work reports success=False, not an error inside a success.

Prod: workspace_files list returned '{"error": "\'>\' not supported ..."}' and the
call was recorded as success=true. A toolset reports failure by raising
``ToolError`` (or any exception); the wrapper turns it into success=False.
"""

import pytest

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.file_toolset import InMemoryStorage
from agentarea_agents_sdk.tools.tasks_toolset import TasksToolset
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_agents_sdk.tools.workspace_files_toolset import WorkspaceFilesToolset


@toolset(namespace="test/refuses", display_name="R", description="d", register=False)
class _Refuses(Toolset):
    @tool_method
    async def run(self) -> str:
        """Refuse the work."""
        raise ToolError("Thing not found")


@pytest.mark.asyncio
async def test_a_tool_error_is_a_failure_with_its_message():
    result = await _Refuses().execute()

    assert result["success"] is False
    assert result["error"] == "Thing not found"
    assert result["result"] == "Thing not found"


@pytest.fixture
def files() -> WorkspaceFilesToolset:
    return WorkspaceFilesToolset(
        storage=InMemoryStorage(), workspace_id="ws-1", workspace_slug="acme"
    )


@pytest.mark.asyncio
async def test_workspace_files_missing_file_is_a_failure(files):
    result = await files.execute(action="get_url", get_url_path="nope.txt")

    assert result["success"] is False
    assert "File not found" in result["error"]


@pytest.mark.asyncio
async def test_workspace_files_delete_of_a_missing_file_is_a_failure(files):
    result = await files.execute(action="delete", delete_path="nope.txt")

    assert result["success"] is False
    assert "File not found" in result["error"]


@pytest.mark.asyncio
async def test_workspace_files_path_escape_is_a_failure(files):
    result = await files.execute(action="list", list_prefix="../other")

    assert result["success"] is False
    assert "escapes workspace scope" in result["error"]


@pytest.mark.asyncio
async def test_workspace_files_storage_error_is_a_failure():
    class BrokenStorage(InMemoryStorage):
        async def list(self, workspace_id, prefix=""):
            raise ConnectionError("store unreachable")

    files = WorkspaceFilesToolset(storage=BrokenStorage(), workspace_id="ws-1")

    result = await files.execute(action="list")

    assert result["success"] is False
    assert "store unreachable" in result["error"]


@pytest.mark.asyncio
async def test_tasks_unknown_task_is_a_failure():
    result = await TasksToolset().execute(
        action="set_status",
        set_status_task_id="00000000-0000-4000-8000-000000000000",
        set_status_status="completed",
    )

    assert result["success"] is False
    assert "Task not found" in result["error"]


async def test_a_tool_error_reaches_an_mcp_client_as_an_error_result():
    from agentarea_agents_sdk.mcp_server import create_mcp_server
    from agentarea_agents_sdk.tools.tool_definition import ToolsetMetadata

    class Lookup(Toolset):
        __toolset_meta__ = ToolsetMetadata(namespace="test/lookup")

        @tool_method
        async def get(self, thing_id: str) -> str:
            """Get a thing."""
            raise ToolError("Thing not found")

    server = create_mcp_server(toolsets=[Lookup()], name="Test", workspace_argument=False)

    result = await server.call_tool_result("lookup_get", {"thing_id": "t-1"})

    assert result.is_error
    assert "Thing not found" in result.content[0].text


async def test_a_failed_base_tool_reaches_an_mcp_client_as_an_error_result():
    from agentarea_agents_sdk.mcp_server import create_mcp_server
    from agentarea_agents_sdk.tools.base_tool import BaseTool

    class Failing(BaseTool):
        name = "failing"
        description = "Always fails"

        def get_schema(self):
            return {"parameters": {"type": "object", "properties": {}}}

        async def execute(self, **kwargs):
            return {"success": False, "result": None, "error": "upstream refused", "tool_name": "failing"}

    server = create_mcp_server(toolsets=[Failing()], name="Test", workspace_argument=False)

    result = await server.call_tool_result("failing", {})

    assert result.is_error
    assert "upstream refused" in result.content[0].text


async def test_a_structured_failure_reaches_an_mcp_client_as_an_error_result():
    from agentarea_agents_sdk.mcp_server import create_mcp_server
    from agentarea_agents_sdk.tools.tool_definition import ToolsetMetadata

    class Command(Toolset):
        __toolset_meta__ = ToolsetMetadata(namespace="test/command")

        @tool_method
        async def run(self, code: int) -> dict:
            """Run a command."""
            return {"success": False, "result": "exit_code: 2", "exit_code": 2}

    server = create_mcp_server(toolsets=[Command()], name="Test", workspace_argument=False)

    result = await server.call_tool_result("command_run", {"code": 2})

    assert result.is_error
    assert "exit_code: 2" in result.content[0].text
