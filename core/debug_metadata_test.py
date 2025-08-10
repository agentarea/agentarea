#!/usr/bin/env python3

import asyncio
import os
import sys
from uuid import uuid4

from sqlalchemy import MetaData

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_metadata_conversion():
    """Debug script to test metadata conversion in isolation."""
    # Import after path setup
    from agentarea_common.auth.test_utils import create_test_user_context
    from agentarea_common.base.models import BaseModel
    from agentarea_tasks.domain.models import TaskCreate
    from agentarea_tasks.infrastructure.repository import TaskRepository
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    # Create in-memory database for testing
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)

    # Create session factory and repository
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    user_context = create_test_user_context()

    async with async_session() as session:
        task_repository = TaskRepository(session, user_context)

        # Test 1: Create TaskCreate with MetaData
        print("=== Test 1: TaskCreate with MetaData ===")
        agent_id = uuid4()
        metadata_obj = MetaData()

        task_create = TaskCreate(
            agent_id=agent_id,
            description="Test task",
            metadata={}  # Start with valid metadata
        )

        print(f"Before assignment: {type(task_create.metadata)} = {task_create.metadata}")

        # Manually set the invalid metadata
        task_create.metadata = metadata_obj

        print(f"After assignment: {type(task_create.metadata)} = {task_create.metadata}")
        print(f"Is it a MetaData object? {isinstance(task_create.metadata, MetaData)}")
        print(f"MetaData() == {{}}: {task_create.metadata == {}}")

        # Test 2: Create task in repository
        print("\n=== Test 2: Repository create_from_data ===")
        try:
            created_task = await task_repository.create_from_data(task_create)
            print(f"Created task metadata type: {type(created_task.metadata)}")
            print(f"Created task metadata value: {created_task.metadata}")
            print(f"Created task metadata == {{}}: {created_task.metadata == {}}")
        except Exception as e:
            print(f"Error creating task: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_metadata_conversion())
