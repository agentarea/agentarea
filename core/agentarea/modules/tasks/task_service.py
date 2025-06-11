"""
Task service for creating and managing tasks with automatic agent execution.
"""

import logging
from typing import Optional, Dict, Any
from uuid import UUID

from agentarea.modules.tasks.domain.task_factory import TaskFactory
from agentarea.modules.tasks.domain.models import Task, TaskType, TaskPriority
from agentarea.common.events.broker import EventBroker
from agentarea.modules.tasks.domain.events import TaskCreated

logger = logging.getLogger(__name__)


class TaskService:
    """Service for creating and managing tasks."""
    
    def __init__(self, event_broker: EventBroker):
        self.event_broker = event_broker
    
    async def create_and_start_test_task(self, agent_id: UUID) -> Task:
        """Create a test task and automatically start agent execution."""
        try:
            # Create test task
            task = TaskFactory.create_test_task(agent_id)
            
            logger.info(f"Created test task {task.id} for agent {agent_id}")
            
            # Publish TaskCreated event to trigger agent execution
            task_created_event = TaskCreated(
                task_id=task.id,
                agent_id=agent_id,
                description=task.description,
                parameters=task.parameters,
                metadata=task.metadata
            )
            
            await self.event_broker.publish(task_created_event)
            logger.info(f"Published TaskCreated event for task {task.id}")
            
            return task
            
        except Exception as e:
            logger.error(f"Failed to create and start test task: {e}", exc_info=True)
            raise
    
    async def create_and_start_simple_task(
        self,
        title: str,
        description: str,
        agent_id: UUID,
        task_type: TaskType = TaskType.ANALYSIS,
        priority: TaskPriority = TaskPriority.MEDIUM,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Task:
        """Create a simple task and automatically start agent execution."""
        try:
            # Create task
            task = TaskFactory.create_simple_task(
                title=title,
                description=description,
                agent_id=agent_id,
                task_type=task_type,
                priority=priority,
                parameters=parameters
            )
            
            logger.info(f"Created task {task.id} '{title}' for agent {agent_id}")
            
            # Publish TaskCreated event to trigger agent execution
            task_created_event = TaskCreated(
                task_id=task.id,
                agent_id=agent_id,
                description=task.description,
                parameters=task.parameters,
                metadata=task.metadata
            )
            
            await self.event_broker.publish(task_created_event)
            logger.info(f"Published TaskCreated event for task {task.id}")
            
            return task
            
        except Exception as e:
            logger.error(f"Failed to create and start task: {e}", exc_info=True)
            raise
    
    async def create_and_start_mcp_task(
        self,
        title: str,
        description: str,
        mcp_server_id: str,
        tool_name: str,
        agent_id: UUID,
        tool_configuration: Optional[Dict[str, Any]] = None,
        priority: TaskPriority = TaskPriority.MEDIUM
    ) -> Task:
        """Create an MCP integration task and start agent execution."""
        try:
            # Create MCP task
            task = TaskFactory.create_mcp_integration_task(
                title=title,
                description=description,
                mcp_server_id=mcp_server_id,
                tool_name=tool_name,
                agent_id=agent_id,
                tool_configuration=tool_configuration,
                priority=priority
            )
            
            logger.info(f"Created MCP task {task.id} for server {mcp_server_id}, tool {tool_name}")
            
            # Publish TaskCreated event to trigger agent execution
            task_created_event = TaskCreated(
                task_id=task.id,
                agent_id=agent_id,
                description=task.description,
                parameters=task.parameters,
                metadata=task.metadata
            )
            
            await self.event_broker.publish(task_created_event)
            logger.info(f"Published TaskCreated event for MCP task {task.id}")
            
            return task
            
        except Exception as e:
            logger.error(f"Failed to create and start MCP task: {e}", exc_info=True)
            raise 