"""In-memory task service implementing CRUD and traversal helpers.

This service is backend-agnostic and can be swapped with other implementations later.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from uuid import UUID

from agentarea_agents_sdk.tasks.tasks import Task, TaskStatus


class InMemoryTaskService:
    """In-memory task management with parent/child relations."""

    def __init__(self):
        self._tasks: dict[UUID, Task] = {}

    # CRUD operations
    def create(
        self,
        title: str,
        description: str = "",
        parent_id: UUID | None = None,
        priority: int = 1,
        metadata: dict | None = None,
    ) -> Task:
        task = Task(
            title=title,
            description=description,
            parent_id=parent_id,
            priority=priority,
            metadata=metadata or {},
        )
        self._tasks[task.id] = task
        return task

    def get(self, task_id: UUID) -> Task | None:
        return self._tasks.get(task_id)

    def update(self, task_id: UUID, **updates) -> Task | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        import datetime

        for k, v in updates.items():
            if hasattr(task, k):
                setattr(task, k, v)
        task.updated_at = datetime.datetime.now().isoformat()
        return task

    def delete(self, task_id: UUID) -> bool:
        # delete descendants first
        for child in list(self.list_subtasks(task_id)):
            self.delete(child.id)
        return self._tasks.pop(task_id, None) is not None

    # Relations and queries
    def add_subtask(
        self,
        parent_id: UUID,
        title: str,
        description: str = "",
        priority: int = 1,
        metadata: dict | None = None,
    ) -> Task | None:
        if parent_id not in self._tasks:
            return None
        return self.create(
            title=title,
            description=description,
            parent_id=parent_id,
            priority=priority,
            metadata=metadata,
        )

    def list_tasks(self, parent_id: UUID | None = None) -> list[Task]:
        if parent_id is None:
            return [t for t in self._tasks.values() if t.parent_id is None]
        return [t for t in self._tasks.values() if t.parent_id == parent_id]

    def list_subtasks(self, task_id: UUID) -> Iterable[Task]:
        return (t for t in self._tasks.values() if t.parent_id == task_id)

    def find_roots(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.parent_id is None]

    def find_descendants(self, task_id: UUID) -> list[Task]:
        result: list[Task] = []
        stack = [task_id]
        while stack:
            current = stack.pop()
            children = [t.id for t in self._tasks.values() if t.parent_id == current]
            result.extend(self._tasks[c] for c in children)
            stack.extend(children)
        return result

    def set_status(self, task_id: UUID, status: TaskStatus) -> Task | None:
        return self.update(task_id, status=status)

    def search(self, text: str) -> list[Task]:
        q = text.lower()
        return [
            t
            for t in self._tasks.values()
            if q in t.title.lower() or q in (t.description or "").lower()
        ]

    # Serialization helpers
    @staticmethod
    def to_dict(task: Task) -> dict:
        data = asdict(task)
        data["id"] = str(task.id)
        data["parent_id"] = str(task.parent_id) if task.parent_id else None
        data["status"] = task.status.value
        return data

    def dump(self) -> list[dict]:
        return [self.to_dict(t) for t in self._tasks.values()]
