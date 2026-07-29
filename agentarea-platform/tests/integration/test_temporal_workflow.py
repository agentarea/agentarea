#!/usr/bin/env python3
"""Simple test to verify Temporal workflow is working."""

import asyncio
import logging
from uuid import uuid4

from agentarea_common.auth.context import UserContext
from agentarea_common.config.database import get_db_session
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.temporal_task_manager import TemporalTaskManager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_temporal_workflow():
    """Test that we can submit a task and it gets processed by Temporal."""

    # Create a simple task
    task = AgentTask(
        id=uuid4(),
        title="Test Task",
        description="A simple test task",
        query="Hello, this is a test task",
        agent_id=uuid4(),
        user_id="test_user",
        workspace_id="test-workspace-456",
        status="pending",
        task_parameters={},
    )

    logger.info(f"Created test task: {task.id}")

    # Create task manager
    async for db_session in get_db_session():
        user_context = UserContext(user_id="test_user", workspace_id="test-workspace-456")
        task_repository = TaskRepository(db_session, user_context)
        task_manager = TemporalTaskManager(task_repository)

        # Persist the task first: submit_task only updates an existing row's status.
        await task_repository.create_task(task_manager._agent_task_to_task(task))

        # Submit task
        logger.info("Submitting task to Temporal...")
        submitted_task = await task_manager.submit_task(task)

        logger.info(f"Task submitted with status: {submitted_task.status}")

        # Check task status
        retrieved_task = await task_manager.get_task(task.id)
        if retrieved_task:
            logger.info(f"Retrieved task status: {retrieved_task.status}")
        else:
            logger.error("Failed to retrieve task")

        return submitted_task


if __name__ == "__main__":
    asyncio.run(test_temporal_workflow())
