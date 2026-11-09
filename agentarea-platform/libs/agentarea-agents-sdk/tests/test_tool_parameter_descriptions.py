"""Every parameter an agent's model is offered says what it is for."""

from typing import Annotated

import pytest
from agentarea_agents_sdk.tools.context_toolset import ContextToolset
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.file_toolset import FileToolset
from agentarea_agents_sdk.tools.shell_toolset import ShellToolset
from agentarea_agents_sdk.tools.web_toolset import WebToolset
from pydantic import Field


def _bare(cls: type[Toolset]) -> Toolset:
    toolset = cls.__new__(cls)
    Toolset.__init__(toolset)
    return toolset


@pytest.mark.parametrize(
    "toolset_cls",
    [ShellToolset, FileToolset, WebToolset, ContextToolset],
)
def test_every_parameter_of_an_agent_toolset_is_described(toolset_cls):
    properties = _bare(toolset_cls).get_openai_function_definition()["function"]["parameters"][
        "properties"
    ]

    descriptions = {
        name: schema.get("description", "").split("] ", 1)[-1].strip()
        for name, schema in properties.items()
    }
    undescribed = [
        name
        for name, description in descriptions.items()
        if not description or description.startswith("Parameter:")
    ]
    assert undescribed == []


def test_an_annotated_description_reaches_the_schema_and_its_type_is_kept():
    class Probe(Toolset):
        @tool_method(effect="read")
        async def run(
            self,
            seconds: Annotated[int | None, Field(description="How long.")] = None,
            plain: str = "",
        ) -> str:
            """Probe."""
            return ""

    properties = _bare(Probe).get_schema()["parameters"]["properties"]

    assert properties["seconds"] == {"description": "How long.", "type": "integer"}
    assert properties["plain"] == {"type": "string"}
