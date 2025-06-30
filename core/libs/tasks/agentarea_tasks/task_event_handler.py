"""Task event handler for updating task status based on agent execution events."""

import logging
from uuid import UUID

from agentarea_common.events.broker import EventBroker
from agentarea_tasks.infrastructure.repository import TaskRepository

logger = logging.getLogger(__name__)


class TaskEventHandler:
    """Handles events from agent execution to update task status."""
    
    def __init__(self, task_repository: TaskRepository, event_broker: EventBroker):
        self.task_repository = task_repository
        self.event_broker = event_broker
    
    async def setup_event_listeners(self):
        """Set up event listeners for task-related events."""
        await self.event_broker.subscribe("TaskStatusChanged", self.handle_task_status_changed)
        await self.event_broker.subscribe("TaskCompleted", self.handle_task_completed)
        await self.event_broker.subscribe("TaskFailed", self.handle_task_failed)
        logger.info("Task event listeners set up successfully")
    
    async def handle_task_status_changed(self, event):
        """Handle TaskStatusChanged events from agent execution."""
        try:
            task_id = UUID(event.task_id)
            new_status = event.new_status.value if hasattr(event.new_status, 'value') else str(event.new_status)
            
            task = await self.task_repository.get(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found for status change event")
                return
                
            task.status = new_status.lower()  # Convert to lowercase for consistency
            await self.task_repository.update(task)
            
            logger.info(f"Updated task {task_id} status to {new_status}")
            
        except Exception as e:
            logger.error(f"Error handling TaskStatusChanged event: {e}", exc_info=True)
    
    async def handle_task_completed(self, event):
        """Handle TaskCompleted events from agent execution."""
        try:
            task_id = UUID(event.task_id)
            
            task = await self.task_repository.get(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found for completion event")
                return
                
            task.status = "completed"
            task.result = event.result if hasattr(event, 'result') else {}
            await self.task_repository.update(task)
            
            logger.info(f"Task {task_id} completed successfully")
            
        except Exception as e:
            logger.error(f"Error handling TaskCompleted event: {e}", exc_info=True)
    
    async def handle_task_failed(self, event):
        """Handle TaskFailed events from agent execution."""
        try:
            task_id = UUID(event.task_id)
            
            task = await self.task_repository.get(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found for failure event")
                return
                
            task.status = "failed"
            task.error_message = event.error_message if hasattr(event, 'error_message') else str(event)
            await self.task_repository.update(task)
            
            logger.error(f"Task {task_id} failed: {task.error_message}")
            
        except Exception as e:
            logger.error(f"Error handling TaskFailed event: {e}", exc_info=True) 