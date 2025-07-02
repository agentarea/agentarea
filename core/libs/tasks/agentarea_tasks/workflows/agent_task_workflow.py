"""Agent Task Workflow Definition.

This workflow handles the execution of agent tasks, including dynamic
activity discovery and long-running task management.
"""

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from google.adk.sessions import InMemorySessionService

    from agentarea_common.infrastructure.database import get_db_session
# from agentarea_common.events.router import get_event_router, create_event_broker_from_router
from agentarea_agents.application.agent_builder_service import AgentBuilderService
from agentarea_agents.application.agent_runner_service import AgentRunnerService
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_common.infrastructure.infisical_factory import get_real_secret_manager
from agentarea_llm.application.service import LLMModelInstanceService
from agentarea_llm.infrastructure.llm_model_instance_repository import (
    LLMModelInstanceRepository,
)
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)

logger = logging.getLogger(__name__)


@workflow.defn(sandboxed=False)  # Отключаем sandbox из-за конфликта с SQLAlchemy
class AgentTaskWorkflow:
    """Main workflow for agent task execution."""

    def __init__(self):
        self.discovered_activities: list[dict[str, Any]] = []
        self.activity_signal_received = False

    @workflow.signal
    async def add_discovered_activity(self, activity_config: dict[str, Any]):
        """Signal handler for dynamically discovered activities."""
        self.discovered_activities.append(activity_config)
        self.activity_signal_received = True
        workflow.logger.info(f"Received signal for new activity: {activity_config['type']}")

    @workflow.run
    async def run(
        self,
        agent_id: str,
        task_id: str,
        query: str,
        user_id: str = "system",
        task_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Main workflow execution logic."""
        workflow.logger.info(f"Starting agent task workflow {task_id} for agent {agent_id}")

        # Activity 1: Validate agent configuration
        validation_result = await workflow.execute_activity(
            validate_agent_activity,
            args=[agent_id],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not validation_result.get("valid", False):
            error_msg = f"Agent validation failed: {validation_result.get('errors', [])}"
            workflow.logger.error(error_msg)
            return {"status": "failed", "error": error_msg, "task_id": task_id}

        # Activity 2: Execute main agent task
        execution_result = await workflow.execute_activity(
            execute_agent_activity,
            args=[agent_id, task_id, query, user_id, task_parameters or {}],
            start_to_close_timeout=timedelta(hours=24),  # Long-running
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=30),
                maximum_interval=timedelta(minutes=10),
            ),
        )

        # Handle dynamic activities discovered during execution
        discovered_activities = execution_result.get("discovered_activities", [])

        for discovered_activity in discovered_activities:
            workflow.logger.info(f"Executing discovered activity: {discovered_activity['type']}")

            activity_result = await workflow.execute_activity(
                execute_dynamic_activity,
                args=[discovered_activity["type"], discovered_activity["config"]],
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # Merge results
            if isinstance(activity_result, dict):
                execution_result.setdefault("dynamic_results", []).append(activity_result)

        # Process any activities discovered via signals
        while self.discovered_activities:
            signal_activity = self.discovered_activities.pop(0)
            workflow.logger.info(f"Executing signal-discovered activity: {signal_activity['type']}")

            signal_result = await workflow.execute_activity(
                execute_dynamic_activity,
                args=[signal_activity["type"], signal_activity["config"]],
                start_to_close_timeout=timedelta(minutes=30),
            )

            if isinstance(signal_result, dict):
                execution_result.setdefault("signal_results", []).append(signal_result)

        return {
            "status": "completed",
            "task_id": task_id,
            "agent_id": agent_id,
            "result": execution_result,
            "execution_time": None,  # Will be filled by executor
        }


# Activity definitions
@activity.defn
async def validate_agent_activity(agent_id: str) -> dict[str, Any]:
    """Validate agent configuration before execution."""
    from agentarea_tasks.workflows.temporal_di import get_activity_deps
    
    async with get_activity_deps() as deps:
        # Validate agent using proper dependency injection
        errors = await deps.agent_builder.validate_agent_config(UUID(agent_id))

        # Send heartbeat for long-running validation (only if in activity context)
        try:
            activity.heartbeat()
        except RuntimeError:
            # Not in activity context - this is fine for direct testing
            pass

        return {"valid": len(errors) == 0, "errors": errors, "agent_id": agent_id}


@activity.defn
async def execute_agent_activity(
    agent_id: str, task_id: str, query: str, user_id: str, task_parameters: dict[str, Any]
) -> dict[str, Any]:
    """Execute the main agent task using existing AgentRunnerService."""
    from agentarea_tasks.workflows.temporal_di import get_activity_deps
    
    # Collect events and results
    events = []
    discovered_activities = []

    logger.info(f"Starting agent execution for task {task_id}")

    async with get_activity_deps() as deps:
        # Execute agent task and collect events
        async for event in deps.agent_runner.run_agent_task(
            agent_id=UUID(agent_id),
            task_id=task_id,
            user_id=user_id,
            query=query,
            task_parameters=task_parameters,
            enable_agent_communication=True,
        ):
            events.append(event)

            # Send periodic heartbeat for long-running tasks (only if in activity context)
            try:
                activity.heartbeat()
            except RuntimeError:
                # Not in activity context - this is fine for direct testing
                pass

            # Detect dynamic activity discovery
            event_type = event.get("event_type", "")

            if event_type == "MCPServerDiscovered":
                discovered_activities.append(
                    {"type": "mcp_tool_call", "config": event.get("mcp_config", {})}
                )
            elif event_type == "ToolDiscovered":
                discovered_activities.append(
                    {"type": "custom_tool", "config": event.get("tool_config", {})}
                )
            elif event_type == "AgentCommunicationRequested":
                discovered_activities.append(
                    {"type": "agent_communication", "config": event.get("communication_config", {})}
                )

        logger.info(f"Agent execution completed for task {task_id}")

        return {
            "status": "completed",
            "events": events,
            "discovered_activities": discovered_activities,
            "event_count": len(events),
            "task_id": task_id,
        }


@activity.defn
async def execute_dynamic_activity(activity_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Execute dynamically discovered activities."""
    logger.info(f"Executing dynamic activity: {activity_type}")

    # Send heartbeat (only if in activity context)
    try:
        activity.heartbeat()
    except RuntimeError:
        # Not in activity context - this is fine for direct testing
        pass

    if activity_type == "mcp_tool_call":
        return await execute_mcp_tool_activity(config)
    elif activity_type == "custom_tool":
        return await execute_custom_tool_activity(config)
    elif activity_type == "agent_communication":
        return await execute_agent_communication_activity(config)
    else:
        logger.warning(f"Unknown dynamic activity type: {activity_type}")
        return {
            "status": "skipped",
            "activity_type": activity_type,
            "reason": "Unknown activity type",
        }


@activity.defn
async def execute_mcp_tool_activity(config: dict[str, Any]) -> dict[str, Any]:
    """Execute MCP tool call activity."""
    # Placeholder for MCP tool execution
    logger.info(f"Executing MCP tool: {config}")

    # Send heartbeat (only if in activity context)
    try:
        activity.heartbeat()
    except RuntimeError:
        # Not in activity context - this is fine for direct testing
        pass

    return {
        "status": "completed",
        "activity_type": "mcp_tool_call",
        "config": config,
        "result": "MCP tool executed successfully",
    }


@activity.defn
async def execute_custom_tool_activity(config: dict[str, Any]) -> dict[str, Any]:
    """Execute custom tool activity."""
    # Placeholder for custom tool execution
    logger.info(f"Executing custom tool: {config}")

    # Send heartbeat (only if in activity context)
    try:
        activity.heartbeat()
    except RuntimeError:
        # Not in activity context - this is fine for direct testing
        pass

    return {
        "status": "completed",
        "activity_type": "custom_tool",
        "config": config,
        "result": "Custom tool executed successfully",
    }


@activity.defn
async def execute_agent_communication_activity(config: dict[str, Any]) -> dict[str, Any]:
    """Execute agent-to-agent communication activity."""
    # Placeholder for agent communication
    logger.info(f"Executing agent communication: {config}")

    # Send heartbeat (only if in activity context)
    try:
        activity.heartbeat()
    except RuntimeError:
        # Not in activity context - this is fine for direct testing
        pass

    return {
        "status": "completed",
        "activity_type": "agent_communication",
        "config": config,
        "result": "Agent communication completed",
    }
