"""Task Execution Service for coordinating task events with agent execution."""
import asyncio
import logging
from typing import Any, Dict
from uuid import UUID

from agentarea.common.events.broker import EventBroker
from agentarea.modules.llm.application.service import LLMModelInstanceService
from agentarea.modules.mcp.application.service import MCPServerInstanceService

from ..infrastructure.repository import AgentRepository
from .agent_builder_service import AgentBuilderService
from .agent_runner_service import AgentRunnerService

logger = logging.getLogger(__name__)


class TaskExecutionService:
    """Service for coordinating task execution with agents."""
    
    def __init__(
        self,
        agent_repository: AgentRepository | None,
        event_broker: EventBroker,
        llm_model_instance_service: LLMModelInstanceService | None,
        mcp_server_instance_service: MCPServerInstanceService | None = None,
        session_service: Any | None = None,
    ):
        self.agent_repository = agent_repository
        self.event_broker = event_broker
        self.llm_model_instance_service = llm_model_instance_service
        self.mcp_server_instance_service = mcp_server_instance_service
        self.session_service = session_service
        
        # Initialize agent builder service only if required dependencies are available
        self.agent_builder_service = None
        if agent_repository and llm_model_instance_service:
            self.agent_builder_service = AgentBuilderService(
                repository=agent_repository,
                event_broker=event_broker,
                llm_model_instance_service=llm_model_instance_service,
                mcp_server_instance_service=mcp_server_instance_service
            )
        
        # Initialize agent runner service only if all dependencies are available
        self.agent_runner_service = None
        if self.agent_builder_service and session_service and agent_repository and llm_model_instance_service:
            self.agent_runner_service = AgentRunnerService(
                repository=agent_repository,
                event_broker=event_broker,
                llm_model_instance_service=llm_model_instance_service,
                session_service=session_service,
                agent_builder_service=self.agent_builder_service
            )

    async def execute_task(
        self,
        task_id: str,
        agent_id: UUID,
        description: str,
        user_id: str | None = None,
        task_parameters: Dict[str, Any] | None = None,
        metadata: Dict[str, Any] | None = None
    ) -> None:
        """Execute a task with the specified agent.
        
        Args:
            task_id: Unique task identifier
            agent_id: UUID of the agent to execute the task
            description: Task description/query
            user_id: User ID requesting the task (defaults to 'system')
            task_parameters: Additional task parameters
            metadata: Task metadata
        """
        if not self.agent_runner_service:
            logger.error("Agent runner service not available - session service and dependencies required")
            return
            
        try:
            # Ensure user_id is not None
            effective_user_id = user_id or (metadata.get("user_id") if metadata else None) or "system"
            query = description or "Execute the assigned task"
            
            logger.info(f"Starting task execution: {task_id} for agent {agent_id}")
            
            # Execute the task and handle events
            async for event in self.agent_runner_service.run_agent_task(
                agent_id=agent_id,
                task_id=task_id,
                user_id=effective_user_id,
                query=query,
                task_parameters=task_parameters or {}
            ):
                # Log the event
                logger.info(f"Task event: {event.get('event_type', 'Unknown')} for task {task_id}")
                
                # Publish task events back to the event broker for other systems
                await self._publish_task_event(event)
                
        except Exception as e:
            logger.error(f"Error executing task {task_id} with agent {agent_id}: {e}", exc_info=True)
            
            # Publish task failure event
            await self._publish_task_event({
                "event_type": "TaskFailed",
                "task_id": task_id,
                "agent_id": str(agent_id),
                "error_message": str(e),
                "error_code": "EXECUTION_ERROR"
            })

    async def _publish_task_event(self, event: Dict[str, Any]) -> None:
        """Publish task execution events back to the event broker."""
        try:
            # Import here to avoid circular imports
            from agentarea.common.events.base_events import DomainEvent
            
            event_type = event.get("event_type")
            task_id = event.get("task_id")
            
            if not task_id:
                logger.warning("Cannot publish event without task_id")
                return
            
            # Create appropriate domain event with proper structure
            # The event data should match the Pydantic models in task_events.py
            event_data = {
                "task_id": task_id,
                "timestamp": event.get("timestamp"),
                "metadata": event.get("metadata", {})
            }
            
            # Add specific fields based on event type
            if event_type == "TaskCreated":
                event_data.update({
                    "agent_id": event.get("agent_id"),
                    "description": event.get("description", "Task created from agent execution")
                })
            elif event_type == "TaskFailed":
                event_data.update({
                    "error_message": event.get("error_message", "Unknown error")
                })
            elif event_type == "TaskCompleted":
                event_data.update({
                    "result": event.get("result", {})
                })
            elif event_type == "TaskStatusChanged":
                event_data.update({
                    "old_status": event.get("old_status", "unknown"),
                    "new_status": event.get("new_status", "unknown")
                })
            elif event_type == "TaskAssigned":
                event_data.update({
                    "agent_id": event.get("agent_id")
                })
            elif event_type == "TaskInputRequired":
                event_data.update({
                    "input_type": event.get("input_type", "text"),
                    "prompt": event.get("prompt", "Input required")
                })
            elif event_type == "TaskArtifactAdded":
                event_data.update({
                    "artifact_id": event.get("artifact_id"),
                    "artifact_type": event.get("artifact_type", "unknown")
                })
            elif event_type == "TaskCanceled":
                event_data.update({
                    "reason": event.get("reason", "Task canceled")
                })
            elif event_type == "TaskUpdated":
                event_data.update({
                    "changes": event.get("changes", {})
                })
            
            # Debug logging to track event structure
            logger.debug(f"Publishing {event_type} event with data: {event_data}")
                
            # Create a domain event with proper structure
            domain_event = DomainEvent(
                event_type=event_type,
                data=event_data
            )
            
            # Additional debug logging
            logger.debug(f"Domain event created: event_type={domain_event.event_type}, data={domain_event.data}")
            
            await self.event_broker.publish(domain_event)
            logger.debug(f"Published {event_type} event for task {task_id}")
                
        except Exception as e:
            logger.error(f"Failed to publish task event: {e}", exc_info=True)

    def execute_task_async(
        self,
        task_id: str,
        agent_id: UUID,
        description: str,
        user_id: str | None = None,
        task_parameters: Dict[str, Any] | None = None,
        metadata: Dict[str, Any] | None = None
    ) -> "asyncio.Task[None]":
        """Execute a task asynchronously and return the task handle.
        
        This method creates a background task for execution without blocking.
        """
        return asyncio.create_task(
            self.execute_task(
                task_id=task_id,
                agent_id=agent_id,
                description=description,
                user_id=user_id,
                task_parameters=task_parameters,
                metadata=metadata
            )
        )

    async def get_agent_config(self, agent_id: UUID) -> Dict[str, Any] | None:
        """Get agent configuration for the specified agent."""
        if not self.agent_builder_service:
            logger.error("Agent builder service not available - cannot get agent config")
            return None
        return await self.agent_builder_service.build_agent_config(agent_id)

    async def validate_agent(self, agent_id: UUID) -> list[str]:
        """Validate agent configuration and return any errors."""
        if not self.agent_builder_service:
            return ["Agent builder service not available"]
        return await self.agent_builder_service.validate_agent_config(agent_id)

    async def get_agent_capabilities(self, agent_id: UUID) -> Dict[str, Any]:
        """Get agent capabilities."""
        if not self.agent_builder_service:
            logger.error("Agent builder service not available - cannot get agent capabilities")
            return {}
        return await self.agent_builder_service.get_agent_capabilities(agent_id) 