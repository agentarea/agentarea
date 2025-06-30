"""Clean Agent Task Workflow with Declarative DI.

This is a refactored version of the agent task workflow that uses
the new dependency injection system for cleaner, more maintainable code.
"""

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from agentarea_tasks.workflows.temporal_di import get_activity_deps

logger = logging.getLogger(__name__)


@workflow.defn
class CleanAgentTaskWorkflow:
    """Clean agent task workflow with declarative DI."""

    def __init__(self):
        self.discovered_activities: list[dict[str, Any]] = []

    @workflow.signal
    async def add_discovered_activity(self, activity_config: dict[str, Any]):
        """Signal handler for dynamically discovered activities."""
        self.discovered_activities.append(activity_config)
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
        workflow.logger.info(f"Starting clean agent task workflow {task_id} for agent {agent_id}")

        # Activity 1: Validate agent configuration
        validation_result = await workflow.execute_activity(
            validate_agent_clean,
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
            execute_agent_clean,
            args=[agent_id, task_id, query, user_id, task_parameters or {}],
            start_to_close_timeout=timedelta(hours=24),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=30),
                maximum_interval=timedelta(minutes=10),
            ),
        )

        return {
            "status": "completed",
            "task_id": task_id,
            "agent_id": agent_id,
            "result": execution_result,
        }


# Clean activity definitions using declarative DI
@activity.defn
async def validate_agent_clean(agent_id: str) -> dict[str, Any]:
    """Validate agent configuration - Clean version with DI.

    This replaces the manual dependency creation with a single
    declarative call to get_activity_deps().
    """
    async with get_activity_deps() as deps:
        # Validate agent using the injected agent builder
        errors = await deps.agent_builder.validate_agent_config(UUID(agent_id))

        activity.heartbeat()  # Send heartbeat for long-running validation

        return {"valid": len(errors) == 0, "errors": errors, "agent_id": agent_id}


@activity.defn
async def execute_agent_clean(
    agent_id: str, task_id: str, query: str, user_id: str, task_parameters: dict[str, Any]
) -> dict[str, Any]:
    """Execute agent task - Clean version with DI.

    This replaces the manual dependency creation with a single
    declarative call to get_activity_deps().
    """
    events = []
    discovered_activities = []

    logger.info(f"Starting clean agent execution for task {task_id}")

    async with get_activity_deps() as deps:
        # Execute agent task using the injected agent runner
        async for event in deps.agent_runner.run_agent_task(
            agent_id=UUID(agent_id),
            task_id=task_id,
            user_id=user_id,
            query=query,
            task_parameters=task_parameters,
            enable_agent_communication=True,
        ):
            events.append(event)
            activity.heartbeat()  # Send periodic heartbeat

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

    logger.info(f"Clean agent execution completed for task {task_id}")

    return {
        "status": "completed",
        "events": events,
        "discovered_activities": discovered_activities,
        "event_count": len(events),
        "task_id": task_id,
    }


@activity.defn
async def execute_dynamic_activity_clean(
    activity_type: str, config: dict[str, Any]
) -> dict[str, Any]:
    """Execute dynamically discovered activities - Clean version."""
    logger.info(f"Executing clean dynamic activity: {activity_type}")

    activity.heartbeat()

    # This would be expanded based on activity type
    # For now, just return a placeholder
    return {"status": "completed", "activity_type": activity_type, "config": config}
