from typing import Literal, Optional, Union
from uuid import UUID
from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """
    Base tool specification.

    This model defines the common attributes that all tools must have,
    including their name, description, and input/output schemas.
    """

    id: Optional[UUID] = Field(None, description="Unique identifier of the tool")
    name: str = Field(description="Name of the tool", example="my-tool")
    description: str = Field(
        description="Description of the tool's functionality",
        example="This tool performs specific operations",
    )
    input_schema: dict = Field(
        description="JSON Schema of the tool's input parameters",
        example={"type": "object", "properties": {"param1": {"type": "string"}}},
    )
    output_schema: dict = Field(
        description="JSON Schema of the tool's output data",
        example={"type": "object", "properties": {"result": {"type": "string"}}},
    )
    type: str = Field(
        description="Tool type identifier, used to determine specific implementation",
        example="mcp",
    )


class MCPToolSpec(ToolSpec):
    """
    MCP (Managed Container Platform) tool specification.

    Extends the base ToolSpec with MCP-specific attributes such as
    version and Docker image information.
    """

    type: Literal["mcp"] = Field(description="Tool type (always 'mcp')")
    version: str = Field(description="Version of the MCP tool", example="1.0.0")
    image: str = Field(
        description="Docker image for the MCP tool",
        example="registry.example.com/mcp-tool:latest",
    )
