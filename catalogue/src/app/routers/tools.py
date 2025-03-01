from uuid import UUID
import uuid
from fastapi import APIRouter, Depends, HTTPException
from typing import Union
from sqlalchemy.orm import Session

from ..schemas.tool import ToolSpec, MCPToolSpec
from ..models.tool import Tool, MCPTool
from ..config import get_db

# Create router with 'tools' tag for Swagger UI grouping
router = APIRouter(tags=["tools"])


@router.post(
    "/upload_tool_spec",
    response_model=dict,
    summary="Upload a tool specification",
    description="""
    Upload a tool specification to the system. 
    Supports both base tools and MCP-specific tools.
    The tool type is determined by the 'type' field in the request body.
    """,
    responses={
        200: {
            "description": "Successfully uploaded tool specification",
            "content": {
                "application/json": {
                    "examples": {
                        "mcp_tool": {
                            "value": {
                                "message": "Uploaded MCP tool: example-tool",
                                "id": "123e4567-e89b-12d3-a456-426614174000",
                            }
                        },
                        "generic_tool": {
                            "value": {
                                "message": "Uploaded generic tool: example-tool",
                                "id": "123e4567-e89b-12d3-a456-426614174000",
                            }
                        },
                    }
                }
            },
        }
    },
)
async def upload_tool_spec(
    tool_spec: Union[MCPToolSpec, ToolSpec], db: Session = Depends(get_db)
) -> dict:
    """
    Upload a tool specification to the system and store it in the database.

    Args:
        tool_spec: Either an MCPToolSpec or base ToolSpec object
        db: Database session

    Returns:
        dict: A message confirming the upload with the tool's name and ID
    """
    # Create base tool model
    id = uuid.uuid4()
    tool = Tool(
        id=id,
        name=tool_spec.name,
        description=tool_spec.description,
        input_schema=tool_spec.input_schema,
        output_schema=tool_spec.output_schema,
        type=tool_spec.type,
    )

    # Handle MCP-specific tool
    if isinstance(tool_spec, MCPToolSpec):
        mcp_tool = MCPTool(
            id=id,
            name=tool_spec.name,
            version=tool_spec.version,
            image=tool_spec.image,
        )
        tool.mcp_tool = mcp_tool

    try:
        db.add(tool)
        db.commit()
        db.refresh(tool)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=400, detail=f"Failed to store tool specification: {str(e)}"
        )

    return {
        "message": f"Uploaded {'MCP' if isinstance(tool_spec, MCPToolSpec) else 'generic'} tool: {tool_spec.name}",
        "id": str(tool.id),
    }


@router.get(
    "/tools/{tool_id}",
    response_model=Union[MCPToolSpec, ToolSpec],
    summary="Get tool specification",
    description="Retrieve a tool specification by its ID",
)
async def get_tool_spec(
    tool_id: UUID, db: Session = Depends(get_db)
) -> Union[MCPToolSpec, ToolSpec]:
    """
    Retrieve a tool specification from the database.

    Args:
        tool_id: UUID of the tool to retrieve
        db: Database session

    Returns:
        Union[MCPToolSpec, ToolSpec]: The tool specification
    """
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Convert to Pydantic model
    if tool.type == "mcp":
        return MCPToolSpec(
            id=tool.id,
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            type=tool.type,
            version=tool.mcp_tool.version,
            image=tool.mcp_tool.image,
        )

    return ToolSpec(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        type=tool.type,
    )
