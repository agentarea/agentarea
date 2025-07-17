"""Task application service."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from agentarea_common.events.broker import EventBroker

from ..domain.events import TaskCreated, TaskStatusChanged
from ..domain.models import Task, TaskCreate, TaskUpdate
from ..infrastructure.repository import TaskRepository


class TaskService:
    """Service for managing task lifecycle."""
    
    def __init__(self, repository: TaskRepository, event_broker: EventBroker):
        self.repository = repository
        self.event_broker = event_broker
    
    async def create_task(
        self,
        agent_id: UUID,
        description: str,
        parameters: dict[str, Any] | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Create a new task."""
        task_data = TaskCreate(
            agent_id=agent_id,
            description=description,
            parameters=parameters or {},
            user_id=user_id,
            metadata=metadata or {},
        )
        
        task = await self.repository.create(task_data)
        
        # Publish task created event
        event = TaskCreated(
            task_id=str(task.id),
            agent_id=agent_id,
            description=description,
            parameters=parameters or {},
            metadata={
                **(metadata or {}),
                "created_at": task.created_at.isoformat(),
                "status": task.status,
                "user_id": user_id,
            },
        )
        await self.event_broker.publish(event)
        
        return task
    
    async def get_task(self, task_id: UUID) -> Task | None:
        """Get a task by ID."""
        return await self.repository.get(task_id)
    
    async def update_task_status(
        self,
        task_id: UUID,
        status: str,
        execution_id: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Task | None:
        """Update task status and related fields."""
        update_data = TaskUpdate(
            status=status,
            execution_id=execution_id,
            result=result,
            error=error,
        )
        
        # Set timestamps based on status
        now = datetime.utcnow()
        if status == "running" and execution_id:
            update_data.started_at = now
        elif status in ["completed", "failed", "cancelled"]:
            update_data.completed_at = now
        
        task = await self.repository.update(task_id, update_data)
        
        if task:
            # Publish status change event
            event = TaskStatusChanged(
                task_id=str(task_id),
                agent_id=task.agent_id,
                old_status="unknown",  # We don't track old status here
                new_status=status,
                execution_id=execution_id,
                metadata={
                    "updated_at": now.isoformat(),
                    "result": result,
                    "error": error,
                },
            )
            await self.event_broker.publish(event)
        
        return task
    
    async def list_agent_tasks(self, agent_id: UUID, limit: int = 100) -> list[Task]:
        """List tasks for an agent."""
        return await self.repository.list_by_agent(agent_id, limit)
    
    async def delete_task(self, task_id: UUID) -> bool:
        """Delete a task."""
        return await self.repository.delete(task_id)