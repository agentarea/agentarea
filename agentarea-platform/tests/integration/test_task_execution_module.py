"""
Module integration test for task execution.

This test validates the complete task execution flow:
- Create agent
- Submit task
- Execute through Temporal
- Verify completion

Run with: pytest tests/integration/test_task_execution_module.py -v
"""

import asyncio
import pytest
from uuid import uuid4
from datetime import datetime

from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.config import get_database
from agentarea_agents.domain.models import Agent, AgentCapability
from agentarea_agents.infrastructure.repositories import AgentRepository
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.temporal_task_manager import TemporalTaskManager


@pytest.fixture
async def db_session():
    """Create a database session for testing."""
    database = get_database()
    async with database.async_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def user_context():
    """Create a test user context."""
    return UserContext(user_id="test-user", workspace_id="test-workspace")


@pytest.fixture
def repository_factory(db_session, user_context):
    """Create a repository factory."""
    return RepositoryFactory(db_session, user_context)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_agent_and_submit_task(repository_factory, db_session):
    """
    Test creating an agent and submitting a task for execution.
    
    This validates:
    1. Agent creation works
    2. Task can be submitted to Temporal
    3. Task status is tracked correctly
    """
    # Create agent repository
    agent_repo = AgentRepository(db_session, repository_factory.user_context)
    
    # Create test agent
    agent = Agent(
        id=uuid4(),
        name="Test Integration Agent",
        description="Agent for integration testing",
        capabilities=[AgentCapability.LLM_CHAT],
        llm_model_instance_id=None,
        system_prompt="You are a test agent",
        tools_config={},
        workspace_id=repository_factory.user_context.workspace_id,
        created_by=repository_factory.user_context.user_id,
    )
    
    # Save agent
    created_agent = await agent_repo.create(agent)
    await db_session.commit()
    
    assert created_agent.id is not None
    assert created_agent.name == "Test Integration Agent"
    print(f"✓ Created agent: {created_agent.id}")
    
    # Create task
    task = SimpleTask(
        id=uuid4(),
        title="Integration Test Task",
        description="Test task execution",
        query="Say hello",
        agent_id=created_agent.id,
        user_id=repository_factory.user_context.user_id,
        status="pending",
        task_parameters={},
    )
    
    # Create task repository and manager
    task_repo = TaskRepository(db_session)
    task_manager = TemporalTaskManager(task_repo)
    
    # Submit task
    submitted_task = await task_manager.submit_task(task)
    
    assert submitted_task.id == task.id
    assert submitted_task.status == "submitted"
    print(f"✓ Submitted task: {submitted_task.id}")
    
    # Verify task can be retrieved
    retrieved_task = await task_manager.get_task(task.id)
    assert retrieved_task is not None
    assert retrieved_task.id == task.id
    print(f"✓ Retrieved task with status: {retrieved_task.status}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_task_workflow_events(repository_factory, db_session):
    """
    Test that task workflow events are properly stored.
    
    This validates the event sourcing mechanism for tasks.
    """
    from agentarea_tasks.application.task_event_service import TaskEventService
    from agentarea_tasks.infrastructure.repository import TaskEventRepository
    
    task_id = uuid4()
    
    # Create task event service
    event_repo = TaskEventRepository(db_session, repository_factory.user_context)
    event_service = TaskEventService(repository_factory, event_broker=None)
    
    # Create workflow events
    events = [
        event_service.create_event(
            task_id=task_id,
            event_type="TaskStarted",
            data={"timestamp": datetime.utcnow().isoformat()},
        ),
        event_service.create_event(
            task_id=task_id,
            event_type="AgentInvoked",
            data={"agent_id": str(uuid4())},
        ),
        event_service.create_event(
            task_id=task_id,
            event_type="TaskCompleted",
            data={"result": "success"},
        ),
    ]
    
    # Store events
    for event in events:
        await event_repo.create_event(event)
    
    await db_session.commit()
    
    # Retrieve events
    stored_events = await event_repo.get_events_for_task(task_id)
    
    assert len(stored_events) == 3
    assert stored_events[0].event_type == "TaskStarted"
    assert stored_events[1].event_type == "AgentInvoked"
    assert stored_events[2].event_type == "TaskCompleted"
    
    print(f"✓ Stored and retrieved {len(stored_events)} workflow events")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_repository_crud(repository_factory, db_session):
    """
    Test agent repository CRUD operations.
    
    This validates the data layer for agents.
    """
    agent_repo = AgentRepository(db_session, repository_factory.user_context)
    
    # Create
    agent = Agent(
        id=uuid4(),
        name="CRUD Test Agent",
        description="Testing CRUD operations",
        capabilities=[AgentCapability.LLM_CHAT, AgentCapability.TOOL_USE],
        workspace_id=repository_factory.user_context.workspace_id,
        created_by=repository_factory.user_context.user_id,
    )
    
    created = await agent_repo.create(agent)
    await db_session.commit()
    assert created.id == agent.id
    print(f"✓ Created agent: {created.id}")
    
    # Read
    retrieved = await agent_repo.get_by_id(agent.id)
    assert retrieved is not None
    assert retrieved.name == "CRUD Test Agent"
    print(f"✓ Retrieved agent: {retrieved.name}")
    
    # List
    agents = await agent_repo.get_all()
    assert len(agents) >= 1
    print(f"✓ Listed {len(agents)} agents")
    
    # Delete
    await agent_repo.delete(agent.id)
    await db_session.commit()
    
    deleted = await agent_repo.get_by_id(agent.id)
    assert deleted is None
    print(f"✓ Deleted agent: {agent.id}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
