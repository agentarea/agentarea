"""A model's tool arguments are checked against the advertised schema before the call.

Prod: the model sent workspace_files list max_items as "50" and the toolset failed
with "'>' not supported between instances of 'str' and 'int'"; it called the shell
without ``command`` and got "bash() missing 1 required positional argument".
"""

from typing import Any

import pytest

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.file_toolset import InMemoryStorage
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_agents_sdk.tools.workspace_files_toolset import WorkspaceFilesToolset


@toolset(namespace="test/one", display_name="O", description="d", register=False)
class _OneMethod(Toolset):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []

    @tool_method
    async def run(
        self,
        command: str,
        limit: int = 10,
        ratio: float = 1.0,
        verbose: bool = False,
        tags: list[str] | None = None,
        extra: Any = None,
    ) -> str:
        """Run something."""
        self.calls.append(
            {
                "command": command,
                "limit": limit,
                "ratio": ratio,
                "verbose": verbose,
                "tags": tags,
                "extra": extra,
            }
        )
        return "ok"


@toolset(namespace="test/many", display_name="M", description="d", register=False)
class _ManyMethods(Toolset):
    def __init__(self) -> None:
        super().__init__()
        self.listed: list[int] = []

    @tool_method
    async def list(self, max_items: int = 200) -> str:
        """List things."""
        self.listed.append(max_items)
        return "listed"

    @tool_method
    async def delete(self, path: str) -> str:
        """Delete a thing."""
        return f"deleted {path}"


@pytest.mark.asyncio
async def test_missing_required_argument_is_named():
    tool = _OneMethod()

    result = await tool.execute(limit=5)

    assert result["success"] is False
    assert "missing required argument 'command'" in result["error"]
    assert "positional argument" not in result["error"]
    assert tool.calls == []


@pytest.mark.asyncio
async def test_missing_prefixed_argument_is_named_as_the_schema_names_it():
    result = await _ManyMethods().execute(action="delete")

    assert result["success"] is False
    assert "missing required argument 'delete_path'" in result["error"]


@pytest.mark.asyncio
async def test_numeric_and_boolean_strings_are_converted():
    tool = _OneMethod()

    result = await tool.execute(command="ls", limit="25", ratio="0.5", verbose="true")

    assert result["success"] is True
    assert tool.calls == [
        {
            "command": "ls",
            "limit": 25,
            "ratio": 0.5,
            "verbose": True,
            "tags": None,
            "extra": None,
        }
    ]


@pytest.mark.asyncio
async def test_a_whole_float_is_an_integer():
    tool = _OneMethod()

    await tool.execute(command="ls", limit=7.0)

    assert tool.calls[0]["limit"] == 7
    assert isinstance(tool.calls[0]["limit"], int)


@pytest.mark.asyncio
async def test_prefixed_integer_string_is_converted():
    tool = _ManyMethods()

    result = await tool.execute(action="list", list_max_items="5")

    assert result["success"] is True
    assert tool.listed == [5]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"limit": "ten"}, "'limit' must be an integer, got 'ten'"),
        ({"limit": "2.5"}, "'limit' must be an integer"),
        ({"limit": True}, "'limit' must be an integer"),
        ({"ratio": "fast"}, "'ratio' must be a number"),
        ({"ratio": "nan"}, "'ratio' must be a number"),
        ({"verbose": "yes"}, "'verbose' must be a boolean"),
        ({"verbose": 1}, "'verbose' must be a boolean"),
        ({"tags": "a,b"}, "'tags' must be an array"),
        ({"command": 42}, "'command' must be a string"),
    ],
)
async def test_invalid_values_are_refused_with_field_and_type(arguments, message):
    tool = _OneMethod()

    result = await tool.execute(**{"command": "ls", **arguments})

    assert result["success"] is False
    assert message in result["error"]
    assert tool.calls == []


@pytest.mark.asyncio
async def test_invalid_prefixed_value_names_the_prefixed_field():
    tool = _ManyMethods()

    result = await tool.execute(action="list", list_max_items="all")

    assert result["success"] is False
    assert "'list_max_items' must be an integer" in result["error"]
    assert tool.listed == []


@pytest.mark.asyncio
async def test_null_for_an_optional_argument_is_accepted():
    tool = _OneMethod()

    result = await tool.execute(command="ls", tags=None)

    assert result["success"] is True


@pytest.mark.asyncio
async def test_parameters_without_an_exact_schema_type_pass_through():
    tool = _OneMethod()

    await tool.execute(command="ls", extra={"any": "shape"})

    assert tool.calls[0]["extra"] == {"any": "shape"}


@pytest.mark.asyncio
async def test_unknown_argument_is_named():
    result = await _OneMethod().execute(command="ls", colour="red")

    assert result["success"] is False
    assert "unknown argument 'colour'" in result["error"]


@pytest.mark.asyncio
async def test_workspace_files_list_accepts_max_items_as_a_string():
    storage = InMemoryStorage()
    await storage.put("ws-1", "a.txt", b"a", "text/plain")
    await storage.put("ws-1", "b.txt", b"b", "text/plain")
    files = WorkspaceFilesToolset(storage=storage, workspace_id="ws-1")

    result = await files.execute(action="list", list_max_items="1")

    assert result["success"] is True
    assert result["result"].count('"path"') == 1
