"""MCP (Model Context Protocol) endpoints for AgentArea API.

This module provides MCP tools for interacting with agents and tasks,
following the FastMCP integration pattern.
"""

import logging
from typing import Any
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.execution_service import ExecutionService
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_common.di.container import get_container
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.task_service import TaskService
from agentarea_tasks.temporal_task_manager import TemporalTaskManager
from fastapi import HTTPException
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Create MCP server
mcp = FastMCP("AgentArea MCP Tools")

async def get_services():
    """Get agent and task services for MCP tools."""
    try:
        # Get the container
        container = get_container()

        # Get dependencies
        repository_factory = await container.get_repository_factory()
        event_broker = await container.get_event_broker()

        # Create agent service
        agent_service = AgentService(repository_factory, event_broker)

        # Create task service components
        task_repository = repository_factory.create_repository(TaskRepository)
        task_manager = TemporalTaskManager(task_repository)

        # Create execution service for workflow service
        execution_service = ExecutionService(repository_factory)
        workflow_service = TemporalWorkflowService(execution_service)

        # Create task service
        task_service = TaskService(
            repository_factory=repository_factory,
            event_broker=event_broker,
            task_manager=task_manager,
            workflow_service=workflow_service,
        )

        return agent_service, task_service

    except Exception as e:
        logger.error(f"Failed to initialize MCP services: {e}")
        raise HTTPException(status_code=500, detail=f"Service initialization failed: {e!s}")


@mcp.tool
async def add_agent(
    name: str,
    description: str,
    instruction: str,
    model_id: str,
    tools_config: dict[str, Any] | None = None,
    events_config: dict[str, Any] | None = None,
    planning: bool | None = None,
) -> dict[str, Any]:
    """Add a new agent to the system.

    Args:
        name: Agent name
        description: Agent description
        instruction: Agent instruction/prompt
        model_id: Model ID to use for the agent
        tools_config: Optional tools configuration
        events_config: Optional events configuration
        planning: Optional planning capability flag

    Returns:
        Dict with agent details including ID, name, and other properties
    """
    try:
        # Get services
        agent_service, _ = await get_services()

        # Create the agent using the service
        agent = await agent_service.create_agent(
            name=name,
            description=description,
            instruction=instruction,
            model_id=model_id,
            tools_config=tools_config,
            events_config=events_config,
            planning=planning,
        )

        # Return agent details
        return {
            "success": True,
            "agent": {
                "id": str(agent.id),
                "name": agent.name,
                "description": agent.description,
                "instruction": agent.instruction,
                "model_id": agent.model_id,
                "status": agent.status,
                "tools_config": agent.tools_config,
                "events_config": agent.events_config,
                "planning": agent.planning,
                "created_at": agent.created_at.isoformat() if agent.created_at else None,
                "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
            },
        }

    except Exception as e:
        logger.error(f"Failed to create agent via MCP: {e}")
        return {
            "success": False,
            "error": {
                "message": str(e),
                "type": type(e).__name__,
            },
        }


@mcp.tool
async def create_task(
    agent_id: str,
    description: str,
    workspace_id: str,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new task for an agent.

    Args:
        agent_id: ID of the agent to assign the task to
        description: Task description
        workspace_id: Workspace ID (required for proper multi-tenancy isolation)
        parameters: Optional task parameters

    Returns:
        Dict with task details including ID, status, and execution info
    """
    try:
        # Get services
        _, task_service = await get_services()

        # Convert agent_id string to UUID
        try:
            agent_uuid = UUID(agent_id)
        except ValueError:
            return {
                "success": False,
                "error": {
                    "message": f"Invalid agent ID format: {agent_id}",
                    "type": "ValueError",
                },
            }

        # Create and execute the task using the service
        task = await task_service.create_and_execute_task_with_workflow(
            agent_id=agent_uuid,
            description=description,
            workspace_id=workspace_id,  # Required parameter, no fallback
            parameters=parameters or {},
            user_id="mcp_user",  # Default user for MCP requests
            enable_agent_communication=True,
        )

        # Return task details
        return {
            "success": True,
            "task": {
                "id": str(task.id),
                "agent_id": str(task.agent_id),
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "parameters": task.task_parameters,
                "result": task.result,
                "error": task.error_message,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "execution_id": task.execution_id,
                "metadata": task.metadata,
            },
        }

    except Exception as e:
        logger.error(f"Failed to create task via MCP: {e}")
        return {
            "success": False,
            "error": {
                "message": str(e),
                "type": type(e).__name__,
            },
        }


@mcp.tool
async def get_agents(
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Get a list of agents.

    Args:
        limit: Maximum number of agents to return (default: 100)
        offset: Number of agents to skip (default: 0)

    Returns:
        Dict with agents list and metadata
    """
    try:
        # Get services
        agent_service, _ = await get_services()

        # Get agents using the service
        agents = await agent_service.list_all(limit=limit, offset=offset)

        # Convert agents to dict format
        agent_list = []
        for agent in agents:
            agent_list.append(
                {
                    "id": str(agent.id),
                    "name": agent.name,
                    "description": agent.description,
                    "instruction": agent.instruction,
                    "model_id": agent.model_id,
                    "status": agent.status,
                    "tools_config": agent.tools_config,
                    "events_config": agent.events_config,
                    "planning": agent.planning,
                    "created_at": agent.created_at.isoformat() if agent.created_at else None,
                    "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
                }
            )

        return {
            "success": True,
            "agents": agent_list,
            "metadata": {
                "limit": limit,
                "offset": offset,
                "total_returned": len(agent_list),
            },
        }

    except Exception as e:
        logger.error(f"Failed to get agents via MCP: {e}")
        return {
            "success": False,
            "error": {
                "message": str(e),
                "type": type(e).__name__,
            },
        }


@mcp.tool
async def get_tasks(
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Get a list of tasks, optionally filtered by agent or status.

    Args:
        agent_id: Optional agent ID to filter tasks
        status: Optional status to filter tasks (pending, running, completed, failed, cancelled)
        limit: Maximum number of tasks to return (default: 100)
        offset: Number of tasks to skip (default: 0)

    Returns:
        Dict with tasks list and metadata
    """
    try:
        # Get services
        _, task_service = await get_services()

        # Convert agent_id to UUID if provided
        agent_uuid = None
        if agent_id:
            try:
                agent_uuid = UUID(agent_id)
            except ValueError:
                return {
                    "success": False,
                    "error": {
                        "message": f"Invalid agent ID format: {agent_id}",
                        "type": "ValueError",
                    },
                }

        # Get tasks using the service
        # Note: The TaskService might need a list method with filtering
        # For now, we'll use the base repository list method
        tasks = await task_service.list_all(limit=limit, offset=offset)

        # Filter tasks by agent_id and status if specified
        filtered_tasks = []
        for task in tasks:
            # Filter by agent_id if specified
            if agent_uuid and task.agent_id != agent_uuid:
                continue

            # Filter by status if specified
            if status and task.status != status:
                continue

            filtered_tasks.append(task)

        # Convert tasks to dict format
        task_list = []
        for task in filtered_tasks[:limit]:  # Apply limit after filtering
            task_list.append(
                {
                    "id": str(task.id),
                    "agent_id": str(task.agent_id),
                    "title": task.title,
                    "description": task.description,
                    "status": task.status,
                    "parameters": task.task_parameters,
                    "result": task.result,
                    "error": task.error_message,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                    "execution_id": task.execution_id,
                    "metadata": task.metadata,
                }
            )

        return {
            "success": True,
            "tasks": task_list,
            "metadata": {
                "agent_id": agent_id,
                "status": status,
                "limit": limit,
                "offset": offset,
                "total_returned": len(task_list),
                "filters_applied": {
                    "agent_id": agent_id is not None,
                    "status": status is not None,
                },
            },
        }

    except Exception as e:
        logger.error(f"Failed to get tasks via MCP: {e}")
        return {
            "success": False,
            "error": {
                "message": str(e),
                "type": type(e).__name__,
            },
        }


mcp_app = mcp.http_app(path="/mcp", transport="streamable-http")
