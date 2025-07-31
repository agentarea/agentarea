#!/usr/bin/env python3
"""
Debug script to test task creation step by step.
"""
import asyncio
import sys
from uuid import UUID, uuid4
from datetime import datetime

# Add the core directory to the path
sys.path.insert(0, '/Users/jamakase/Projects/startup/agentarea/core')

from agentarea_common.config import get_database
from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.domain.models import Task


async def test_task_creation():
    """Test task creation step by step."""
    print("🔍 Testing task creation step by step...")
    
    # Step 1: Test database connection
    print("\n1. Testing database connection...")
    try:
        database = get_database()
        async with database.async_session_factory() as session:
            print("✅ Database connection successful")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return
    
    # Step 2: Test user context creation
    print("\n2. Testing user context creation...")
    try:
        user_context = UserContext(
            user_id="test-user-123",
            workspace_id="default"
        )
        print(f"✅ User context created: {user_context}")
    except Exception as e:
        print(f"❌ User context creation failed: {e}")
        return
    
    # Step 3: Test repository creation
    print("\n3. Testing repository creation...")
    try:
        async with database.async_session_factory() as session:
            repository = TaskRepository(session, user_context)
            print("✅ Repository created successfully")
    except Exception as e:
        print(f"❌ Repository creation failed: {e}")
        return
    
    # Step 4: Test task domain object creation
    print("\n4. Testing task domain object creation...")
    try:
        task_id = uuid4()
        agent_id = UUID("31589c71-f085-4a98-8a62-878f11e8a699")
        
        task_domain = Task(
            id=task_id,
            agent_id=agent_id,
            description="Test task for debugging",
            parameters={"test": "value"},
            status="pending",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            metadata={}
        )
        print(f"✅ Task domain object created: {task_domain.id}")
    except Exception as e:
        print(f"❌ Task domain object creation failed: {e}")
        return
    
    # Step 5: Test task persistence
    print("\n5. Testing task persistence...")
    try:
        async with database.async_session_factory() as session:
            repository = TaskRepository(session, user_context)
            created_task = await repository.create_task(task_domain)
            print(f"✅ Task persisted successfully: {created_task.id}")
            
            # Step 6: Test task retrieval
            print("\n6. Testing task retrieval...")
            retrieved_task = await repository.get_by_id(created_task.id)
            if retrieved_task:
                print(f"✅ Task retrieved successfully: {retrieved_task.id}")
            else:
                print("❌ Task retrieval failed: task not found")
                
    except Exception as e:
        print(f"❌ Task persistence failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n🎉 All task creation steps completed successfully!")


if __name__ == "__main__":
    asyncio.run(test_task_creation())