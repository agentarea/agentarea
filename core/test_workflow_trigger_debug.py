#!/usr/bin/env python3
"""
Debug script to test if workflows are being triggered.
"""
import asyncio
import sys
from uuid import UUID, uuid4

# Add the core directory to the path
sys.path.insert(0, '/Users/jamakase/Projects/startup/agentarea/core')

from agentarea_common.config import get_database
from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.temporal_task_manager import TemporalTaskManager
from agentarea_tasks.domain.models import SimpleTask


async def test_workflow_trigger():
    """Test if workflow is being triggered."""
    print("🔍 Testing workflow trigger step by step...")
    
    # Step 1: Create task in database
    print("\n1. Creating task in database...")
    try:
        database = get_database()
        user_context = UserContext(
            user_id="test-user-123",
            workspace_id="default"
        )
        
        agent_id = UUID("31589c71-f085-4a98-8a62-878f11e8a699")
        
        simple_task = SimpleTask(
            id=uuid4(),
            agent_id=agent_id,
            title="Debug Workflow Trigger",
            description="Test task to check workflow triggering",
            query="Calculate 50 + 25",
            user_id="test-user-123",
            workspace_id="default",
            task_parameters={"test": "value"},
            status="pending"
        )
        
        async with database.async_session_factory() as session:
            task_repository = TaskRepository(session, user_context)
            
            # Convert SimpleTask to Task domain model
            from agentarea_tasks.domain.models import Task
            from datetime import datetime
            
            task_domain = Task(
                id=simple_task.id,
                agent_id=simple_task.agent_id,
                description=simple_task.description,
                parameters=simple_task.task_parameters,
                status=simple_task.status,
                result=simple_task.result,
                error=simple_task.error_message,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                started_at=simple_task.started_at,
                completed_at=simple_task.completed_at,
                execution_id=simple_task.execution_id,
                metadata=simple_task.metadata,
            )
            
            created_task = await task_repository.create_task(task_domain)
            print(f"✅ Task created in database: {created_task.id}")
            
    except Exception as e:
        print(f"❌ Task creation failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 2: Test workflow triggering
    print("\n2. Testing workflow triggering...")
    try:
        async with database.async_session_factory() as session:
            task_repository = TaskRepository(session, user_context)
            task_manager = TemporalTaskManager(task_repository)
            
            # This should trigger the workflow
            print("   Calling task_manager.submit_task()...")
            
            # Convert Task back to SimpleTask for the manager
            simple_task_for_manager = SimpleTask(
                id=created_task.id,
                agent_id=created_task.agent_id,
                title="Debug Workflow Trigger",
                description=created_task.description,
                query="Calculate 50 + 25",
                user_id="test-user-123",
                workspace_id="default",
                task_parameters=created_task.parameters,
                status=created_task.status
            )
            
            execution_result = await task_manager.submit_task(simple_task_for_manager)
            
            print(f"✅ Workflow triggered successfully!")
            print(f"   - Task ID: {execution_result.id}")
            print(f"   - Status: {execution_result.status}")
            print(f"   - Execution ID: {execution_result.execution_id}")
            
    except Exception as e:
        print(f"❌ Workflow triggering failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n🎉 Workflow trigger test completed!")


if __name__ == "__main__":
    asyncio.run(test_workflow_trigger())