#!/usr/bin/env python3

from uuid import uuid4

from agentarea_tasks.domain.models import TaskCreate
from sqlalchemy import MetaData

# Test manual assignment after object creation
print("Testing manual assignment after object creation...")
task_create = TaskCreate(
    agent_id=uuid4(),
    description="Test task",
    parameters={"test": "value"},
    metadata={}  # Start with valid metadata
)

print(f"Initial metadata: {task_create.metadata} (type: {type(task_create.metadata)})")

# This is what the test does - manual assignment
metadata_obj = MetaData()
print(f"Setting metadata to: {metadata_obj} (type: {type(metadata_obj)})")
task_create.metadata = metadata_obj

print(f"After assignment: {task_create.metadata} (type: {type(task_create.metadata)})")
print(f"Is metadata still MetaData? {isinstance(task_create.metadata, MetaData)}")
print(f"Is metadata a dict? {isinstance(task_create.metadata, dict)}")
