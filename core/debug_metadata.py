#!/usr/bin/env python3

import sys

sys.path.insert(0, 'libs/tasks')

from uuid import uuid4

from agentarea_tasks.domain.models import TaskCreate
from sqlalchemy import MetaData


def test_metadata_assignment():
    print("Testing metadata assignment...")

    # Create TaskCreate with valid metadata
    task_create = TaskCreate(
        agent_id=uuid4(),
        description="Test task",
        parameters={"test": "value"},
        metadata={}  # Start with valid metadata
    )

    print(f"Initial metadata: {task_create.metadata} (type: {type(task_create.metadata)})")

    # Manually set invalid metadata
    metadata_obj = MetaData()
    print(f"Setting metadata to: {metadata_obj} (type: {type(metadata_obj)})")

    task_create.metadata = metadata_obj

    print(f"After assignment: {task_create.metadata} (type: {type(task_create.metadata)})")

    # Check if it's still the MetaData object
    print(f"Is metadata still MetaData? {isinstance(task_create.metadata, MetaData)}")
    print(f"Is metadata a dict? {isinstance(task_create.metadata, dict)}")

if __name__ == "__main__":
    test_metadata_assignment()
