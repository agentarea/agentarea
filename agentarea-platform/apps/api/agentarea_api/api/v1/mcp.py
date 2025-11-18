"""MCP (Model Context Protocol) endpoints for AgentArea API.

DEPRECATED: This module's manual MCP tool implementations have been deprecated
in favor of FastAPI-MCP library integration which automatically converts FastAPI
endpoints into MCP tools.

Legacy FastMCP-based tools are commented out below. The application now uses
FastAPI-MCP to expose REST API endpoints as MCP tools without manual tool registration.

See /llm/mcp endpoint for the current FastAPI-MCP server.
"""

import logging

logger = logging.getLogger(__name__)

"""
DEPRECATED FASTMCP IMPLEMENTATION - KEPT FOR REFERENCE ONLY

The following manual MCP tool implementations have been replaced with FastAPI-MCP
library which automatically converts FastAPI endpoints to MCP tools.

Original implementations:
- add_agent: Create a new agent
- create_task: Create a new task
- get_agents: List agents
- get_tasks: List tasks
- create_mcp_server_instance: Create MCP server instance
- list_mcp_server_instances: List MCP server instances
- get_mcp_server_instance: Get MCP server instance details
- update_mcp_server_instance: Update MCP server instance
- delete_mcp_server_instance: Delete MCP server instance
- list_mcp_servers: List MCP server specifications
- get_mcp_server: Get MCP server specification details
- update_agent: Update an agent
- delete_agent: Delete an agent
- get_agent_details: Get full agent details
- create_llm_model_instance: Create LLM model instance
- list_llm_model_instances: List LLM model instances
- get_llm_model_instance: Get LLM model instance details
- update_llm_model_instance: Update LLM model instance
- delete_llm_model_instance: Delete LLM model instance

All these tools are now automatically exposed via FastAPI-MCP by converting
the REST API endpoints in the protected_v1_router and public_v1_router.

Original serialization helper kept below for reference:

def serialize_model(model: Any) -> dict[str, Any]:
    '''Serialize a domain model to a JSON-friendly dict.'''
    if hasattr(model, "to_dict"):
        data = model.to_dict()
    else:
        data = {}
        for key, value in model.__dict__.items():
            if not key.startswith("_"):
                data[key] = value

    for key, value in data.items():
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()

    return data


async def get_services():
    '''Get all services for MCP tools (DEPRECATED).'''
    # This function was used to inject services into MCP tools
    # No longer needed with FastAPI-MCP approach
    pass
"""
