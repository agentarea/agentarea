#!/usr/bin/env python3
"""
Debug script to test task service and workflow triggering.
"""
import asyncio
import sys
from uuid import UUID, uuid4

# Add the core directory to the path
sys.path.insert(0, '/Users/jamakase/Projects/startup/agentarea/core')

from agentarea_common.config import get_database
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.events.broker import EventBroker
from agentarea_tasks.task_service import TaskService
from agentarea_tasks.temporal_task_manager import TemporalTaskManager
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.domain.models import SimpleTask


async def test_task_service():
    """Test task service step by step."""
    print("🔍 Testing task service step by step...")
    
    # Step 1: Create all dependencies
    print("\n1. Creating task service dependencies...")
    try:
        database = get_database()
        user_context = UserContext(
            user_id="test-user-123",
            workspace_id="default"
        )
        
        async with database.async_session_factory() as session:
            # Create repository factory
            repository_factory = RepositoryFactory(session, user_context)
            
            # Create event broker
            event_broker = EventBroker()
            
            # Create task repository and task manager
            task_repository = repository_factory.create_repository(TaskRepository)
            task_manager = TemporalTaskManager(task_repository)
            
            # Create task service
            task_service = TaskService(
                repository_factory=repository_factory,
                event_broker=event_broker,
                task_manager=task_manager,
                workflow_service=None  # We'll test without workflow service first
            )
            print("✅ Task service created successfully")
    except Exception as e:
        print(f"❌ Task service creation failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 2: Create SimpleTask
    print("\n2. Creating SimpleTask...")
    try:
        agent_id = UUID("31589c71-f085-4a98-8a62-878f11e8a699")
        
        simple_task = SimpleTask(
            id=uuid4(),
            agent_id=agent_id,
            title="Debug Task",
            description="Test task for debugging service layer",
            query="Calculate 50 + 25",
            user_id="test-user-123",
            workspace_id="default",
            task_parameters={"test": "value"},
            status="pending"
        )
        print(f"✅ SimpleTask created: {simple_task.id}")
    except Exception as e:
        print(f"❌ SimpleTask creation failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 3: Test task creation through service
    print("\n3. Testing task creation through service...")
    try:
        async with database.async_session_factory() as session:
            # Recreate all dependencies for this session
            repository_factory = RepositoryFactory(session, user_context)
            event_broker = EventBroker()
            task_repository = repository_factory.create_repository(TaskRepository)
            task_manager = TemporalTaskManager(task_repository)
            
            task_service = TaskService(
                repository_factory=repository_factory,
                event_broker=event_broker,
                task_manager=task_manager,
                workflow_service=None
            )
            
            created_task = await task_service.create_task(simple_task)
            print(f"✅ Task created through service: {created_task.id}")
            
            # Check if workflow was triggered
            print(f"   - Task status: {created_task.status}")
            print(f"   - Execution ID: {created_task.execution_id}")
            
    except Exception as e:
        print(f"❌ Task creation through service failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n🎉 Task service test completed!")


if __name__ == "__main__":
    asyncio.run(test_task_service())