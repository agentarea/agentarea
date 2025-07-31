"""Task service for AgentArea platform.

High-level service that orchestrates task management by:
1. Handling task persistence through TaskRepository
2. Delegating task execution to injected TaskManager
3. Managing task lifecycle and events
4. Validating agent existence before task submission
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import UUID

from agentarea_common.events.broker import EventBroker

from .domain.base_service import BaseTaskService
from .domain.interfaces import BaseTaskManager
from .domain.models import SimpleTask
from .infrastructure.repository import TaskRepository

if TYPE_CHECKING:
    from agentarea_agents.infrastructure.repository import AgentRepository
    from agentarea_common.base import RepositoryFactory

logger = logging.getLogger(__name__)


class TaskService(BaseTaskService):
    """High-level service for task management that orchestrates persistence and execution."""

    def __init__(
        self,
        repository_factory: "RepositoryFactory",
        event_broker: EventBroker,
        task_manager: BaseTaskManager,
        workflow_service: Any | None = None,
    ):
        """Initialize with repository factory, event broker, task manager, and optional dependencies."""
        from agentarea_common.base import RepositoryFactory
        
        # Create repositories using factory
        task_repository = repository_factory.create_repository(TaskRepository)
        super().__init__(task_repository, event_broker)
        
        self.repository_factory = repository_factory
        self.task_manager = task_manager
        self.workflow_service = workflow_service
        
        # Create agent repository using factory for validation
        try:
            from agentarea_agents.infrastructure.repository import AgentRepository
            self.agent_repository = repository_factory.create_repository(AgentRepository)
        except ImportError:
            self.agent_repository = None

    async def _validate_agent_exists(self, agent_id: UUID) -> None:
        """Validate that the agent exists before processing tasks.

        Args:
            agent_id: The agent ID to validate

        Raises:
            ValueError: If agent doesn't exist or agent_repository is not available
        """
        if not self.agent_repository:
            logger.warning("Agent repository not available - skipping agent validation")
            return

        agent = await self.agent_repository.get(agent_id)
        if not agent:
            raise ValueError(f"Agent with ID {agent_id} does not exist")

    async def create_task_from_params(
        self,
        title: str,
        description: str,
        query: str,
        user_id: str,
        agent_id: UUID,
        workspace_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
    ) -> SimpleTask:
        """Create a new task from parameters."""
        task = SimpleTask(
            title=title,
            description=description,
            query=query,
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            task_parameters=task_parameters or {},
            status="submitted",
        )
        return await self.create_task(task)

    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Submit a task for execution through the task manager.

        This method validates the agent exists before submitting to avoid
        failures later in the Temporal workflow.
        """
        # Validate agent exists first (fail fast)
        await self._validate_agent_exists(task.agent_id)

        # First persist the task
        created_task = await self.create_task(task)

        # Then submit to task manager for execution
        return await self.task_manager.submit_task(created_task)

    async def cancel_task(self, task_id: UUID) -> bool:
        """Cancel a task."""
        return await self.task_manager.cancel_task(task_id)

    async def get_user_tasks(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> List[SimpleTask]:
        """Get tasks for a specific user."""
        return await self.list_tasks(user_id=user_id, limit=limit, offset=offset)

    async def get_agent_tasks(
        self, agent_id: UUID, limit: int = 100, offset: int = 0, creator_scoped: bool = False
    ) -> List[SimpleTask]:
        """Get tasks for a specific agent."""
        # Use the repository's list_all method with creator_scoped parameter
        if hasattr(self.task_repository, 'list_all'):
            return await self.task_repository.list_all(
                creator_scoped=creator_scoped,
                limit=limit,
                offset=offset,
                agent_id=agent_id
            )
        else:
            # Fallback for repositories that don't support workspace scoping
            return await self.list_tasks(agent_id=agent_id, limit=limit, offset=offset)

    async def get_task_status(self, task_id: UUID) -> str | None:
        """Get task status."""
        task = await self.get_task(task_id)
        return task.status if task else None

    async def get_task_result(self, task_id: UUID) -> Any | None:
        """Get task result."""
        task = await self.get_task(task_id)
        return task.result if task else None

    async def update_task_status(
        self,
        task_id: UUID,
        status: str,
        execution_id: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> SimpleTask | None:
        """Update task status and related fields.

        This method provides compatibility with the application layer TaskService
        that was removed during refactoring.

        Args:
            task_id: The task ID to update
            status: The new status
            execution_id: Optional execution ID
            result: Optional task result
            error: Optional error message

        Returns:
            The updated task if found, None otherwise
        """
        task = await self.get_task(task_id)
        if not task:
            return None

        # Update the task using the SimpleTask's update_status method
        task.update_status(
            status,
            execution_id=execution_id,
            result=result,
            error_message=error
        )

        # Persist the update
        return await self.update_task(task)

    async def list_agent_tasks(self, agent_id: UUID, limit: int = 100, creator_scoped: bool = False) -> List[SimpleTask]:
        """List tasks for an agent.

        This method provides compatibility with the application layer TaskService
        that was removed during refactoring.

        Args:
            agent_id: The agent ID to get tasks for
            limit: Maximum number of tasks to return
            creator_scoped: If True, only return tasks created by current user

        Returns:
            List of tasks for the agent
        """
        return await self.get_agent_tasks(agent_id, limit=limit, creator_scoped=creator_scoped)

    async def list_agent_tasks_with_workflow_status(self, agent_id: UUID, limit: int = 100, creator_scoped: bool = False) -> List[SimpleTask]:
        """List tasks for an agent enriched with workflow status.

        Args:
            agent_id: The agent ID to get tasks for
            limit: Maximum number of tasks to return
            creator_scoped: If True, only return tasks created by current user

        Returns:
            List of tasks for the agent with current workflow status
        """
        tasks = await self.list_agent_tasks(agent_id, limit, creator_scoped=creator_scoped)

        if not self.workflow_service:
            logger.warning("Workflow service not available - returning tasks without workflow enrichment")
            return tasks

        # Enrich each task with workflow status
        enriched_tasks = []
        for task in tasks:
            enriched_task = await self._enrich_task_with_workflow_status(task)
            enriched_tasks.append(enriched_task)

        return enriched_tasks

    async def get_task_with_workflow_status(self, task_id: UUID) -> SimpleTask | None:
        """Get a task enriched with workflow status.

        Args:
            task_id: The task ID to get

        Returns:
            Task with current workflow status if found, None otherwise
        """
        task = await self.get_task(task_id)
        if not task:
            return None

        if not self.workflow_service:
            logger.warning("Workflow service not available - returning task without workflow enrichment")
            return task

        return await self._enrich_task_with_workflow_status(task)

    async def _enrich_task_with_workflow_status(self, task: SimpleTask) -> SimpleTask:
        """Enrich a task with current workflow status.

        Args:
            task: The task to enrich

        Returns:
            Task with updated status and result from workflow
        """
        if not task.execution_id or not self.workflow_service:
            return task

        try:
            workflow_status = await self.workflow_service.get_workflow_status(task.execution_id)
            if workflow_status.get("status") != "unknown":
                # Update task with workflow status
                task.status = workflow_status.get("status", task.status)
                if workflow_status.get("result"):
                    task.result = workflow_status.get("result")
        except Exception as e:
            logger.debug(f"Could not get workflow status for task {task.id}: {e}")

        return task

    # Legacy methods for backward compatibility
    async def execute_task(
        self,
        task_id: UUID,
        enable_agent_communication: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a task (legacy method - prefer using submit_task)."""
        # Get the task
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        logger.info(f"Starting execution of task {task_id}")

        # Update task status to working
        task.status = "working"
        await self.update_task(task)

        try:
            # For now, just yield a completion event
            # In a real implementation, this would stream events from the task manager
            yield {"event_type": "TaskStarted", "task_id": str(task_id)}

            # Submit to task manager
            await self.task_manager.submit_task(task)

        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}")
            # Update task with error
            task.status = "failed"
            task.error_message = str(e)
            await self.update_task(task)
            yield {"event_type": "TaskFailed", "task_id": str(task_id), "error": str(e)}
            raise

    async def create_and_execute_task_with_workflow(
        self,
        agent_id: UUID,
        description: str,
        parameters: dict[str, Any] | None = None,
        user_id: str | None = None,
        enable_agent_communication: bool = True,
    ) -> SimpleTask:
        """Create a task and execute it using workflow.

        Args:
            agent_id: The agent to execute the task
            description: Task description
            parameters: Task parameters
            user_id: User ID (defaults to "api_user")
            enable_agent_communication: Whether to enable agent communication

        Returns:
            Created task with workflow execution info
        """
        from uuid import uuid4

        # Validate agent exists first
        await self._validate_agent_exists(agent_id)

        # Generate task ID
        task_id = uuid4()

        # Get agent name for metadata (if available)
        agent_name = "unknown"
        if self.agent_repository:
            try:
                agent = await self.agent_repository.get(agent_id)
                if agent:
                    agent_name = agent.name
            except Exception as e:
                logger.warning(f"Could not get agent name for {agent_id}: {e}")

        # Create task
        task = SimpleTask(
            id=task_id,
            title=description,
            description=description,
            query=description,
            user_id=user_id or "api_user",
            agent_id=agent_id,
            status="pending",
            task_parameters=parameters or {},
            metadata={
                "created_via": "api",
                "agent_name": agent_name,
                "enable_agent_communication": enable_agent_communication,
            },
        )

        # Store task
        stored_task = await self.create_task(task)

        # Publish TaskCreated event - temporarily disabled due to event creation issue
        # from .domain.events import TaskCreated
        # task_created_event = TaskCreated(
        #     task_id=str(task_id),
        #     agent_id=str(agent_id),
        #     description=description,
        #     parameters=parameters or {},
        # )
        # await self._publish_task_event(task_created_event)

        # Set initial status
        stored_task.status = "pending"

        # Execute task using the task manager (which uses AgentExecutionWorkflow)
        try:
            # Submit task through task manager
            executed_task = await self.task_manager.submit_task(stored_task)
            
            # Update stored task with execution info
            stored_task.status = executed_task.status
            stored_task.execution_id = executed_task.execution_id
            
            logger.info(f"Task {task_id} submitted successfully with status {executed_task.status}")

        except Exception as e:
            logger.error(f"Failed to submit task: {e}")
            stored_task.status = "failed"
            stored_task.result = {"error": str(e), "error_type": "task_submission_failed"}

        return stored_task

    async def create_and_execute_task(
        self,
        title: str,
        description: str,
        query: str,
        user_id: str,
        agent_id: UUID,
        task_parameters: dict[str, Any] | None = None,
        enable_agent_communication: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Create a task and immediately start execution."""
        # Create the task
        task = await self.create_task_from_params(
            title=title,
            description=description,
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            task_parameters=task_parameters,
        )

        # Execute it
        async for event in self.execute_task(task.id, enable_agent_communication):
            yield event

    async def stream_task_events(self, task_id: UUID, include_history: bool = True) -> AsyncGenerator[dict[str, Any], None]:
        """Stream real-time events for a task using the injected EventBroker.

        This provides a clean interface for SSE endpoints to consume events
        without knowing about specific broker implementations.

        Args:
            task_id: The task to stream events for
            include_history: Whether to include past events before streaming new ones

        Yields:
            dict: Event data in a consistent format
        """
        # Set up event listener for this task
        task_events = asyncio.Queue()
        listener_task = None

        async def event_listener():
            """Listen for workflow events using direct Redis pubsub."""
            import json
            
            pubsub = None
            try:
                logger.info(f"Started event listener for task {task_id} using Redis pubsub")

                # Access the underlying Redis broker from the EventBroker
                if not hasattr(self.event_broker, 'redis_broker'):
                    raise AttributeError("EventBroker does not have redis_broker attribute")
                
                redis_broker = self.event_broker.redis_broker
                
                # Ensure Redis broker is connected
                if not hasattr(redis_broker, '_connection') or redis_broker._connection is None:
                    await redis_broker.connect()
                
                # Get the underlying Redis connection
                # For FastStream RedisBroker, try different possible connection attributes
                redis_connection = None
                for attr in ['_connection', 'connection', 'client', '_client', 'redis']:
                    if hasattr(redis_broker, attr):
                        redis_connection = getattr(redis_broker, attr)
                        if redis_connection is not None:
                            break
                
                if redis_connection is None:
                    raise AttributeError("Could not access underlying Redis connection from FastStream RedisBroker")
                
                # Create pubsub connection
                pubsub = redis_connection.pubsub()
                
                # Subscribe to workflow patterns
                await pubsub.psubscribe("workflow.*")
                
                logger.info(f"Subscribed to workflow.* patterns for task {task_id}")
                
                # Listen for messages
                async for message in pubsub.listen():
                    try:
                        if message['type'] == 'pmessage':
                            # Parse the JSON event data
                            channel = message['channel'].decode('utf-8') if isinstance(message['channel'], bytes) else message['channel']
                            data = message['data']
                            
                            if isinstance(data, bytes):
                                data = data.decode('utf-8')
                            
                            if isinstance(data, str):
                                try:
                                    event_data = json.loads(data)
                                except json.JSONDecodeError:
                                    logger.warning(f"Failed to parse JSON event data: {data}")
                                    continue
                            else:
                                event_data = data
                            
                            # Handle FastStream message structure: {"data": "JSON_STRING", "headers": {...}}
                            actual_event_data = event_data
                            if isinstance(event_data, dict) and "data" in event_data and isinstance(event_data["data"], str):
                                # The actual event is a JSON string inside the "data" field
                                try:
                                    actual_event_data = json.loads(event_data["data"])
                                except json.JSONDecodeError:
                                    logger.warning(f"Failed to parse inner JSON event data: {event_data['data']}")
                                    continue
                            
                            # Filter events for this specific task
                            task_id_str = str(task_id)
                            if (isinstance(actual_event_data, dict) and 
                                actual_event_data.get('data', {}).get('aggregate_id') == task_id_str):
                                
                                # Convert to DomainEvent-like format for compatibility
                                domain_event = {
                                    'event_type': channel,
                                    'event_data': actual_event_data,
                                    'timestamp': datetime.now(UTC)
                                }
                                
                                await task_events.put(domain_event)
                                logger.debug(f"Queued event for task {task_id}: {channel}")
                                
                    except Exception as e:
                        logger.warning(f"Failed to process Redis message: {e}")
                        continue
                            
            except Exception as e:
                logger.error(f"Event listener failed for task {task_id}: {e}")
                # Send error to the queue
                await task_events.put({
                    "error": str(e),
                    "task_id": str(task_id),
                    "agent_id": "unknown",
                    "execution_id": "unknown",
                    "timestamp": datetime.now(UTC).isoformat()
                })
            finally:
                # Clean up pubsub connection
                if pubsub:
                    try:
                        await pubsub.punsubscribe("workflow.*")
                        await pubsub.close()
                        logger.debug(f"Cleaned up pubsub connection for task {task_id}")
                    except Exception as e:
                        logger.warning(f"Failed to cleanup pubsub connection: {e}")

        # Start the event listener task
        listener_task = asyncio.create_task(event_listener())

        try:
            # Send historical events first if requested
            if include_history:
                historical_events = await self._get_historical_events(task_id)
                for event in historical_events:
                    yield event

            # Stream real-time events
            while True:
                try:
                    # Wait for event with timeout to allow cleanup
                    event = await asyncio.wait_for(task_events.get(), timeout=30.0)
                    
                    # Check if this is an error event (dict format)
                    if isinstance(event, dict) and "error" in event:
                        yield {
                            "event_type": "listener_error",
                            "timestamp": event.get("timestamp"),
                            "data": {
                                "error": event["error"],
                                "task_id": event.get("task_id", str(task_id)),
                                "agent_id": event.get("agent_id", "unknown"),
                                "execution_id": event.get("execution_id", "unknown"),
                            }
                        }
                        break  # Stop streaming on listener error
                    
                    # Transform and yield the event (both old DomainEvent format and new dict format)
                    if hasattr(event, 'event_type'):
                        # Old DomainEvent format
                        event_data = event.event_data if hasattr(event, 'event_data') else {}
                        # Handle nested data structure where actual data is in 'data' dict
                        actual_data = event_data.get('data', event_data) if isinstance(event_data, dict) else event_data
                        yield {
                            "event_type": event.event_type.replace("workflow.", ""),  # Remove prefix
                            "timestamp": event.timestamp.isoformat() if hasattr(event, 'timestamp') else datetime.now(UTC).isoformat(),
                            "data": actual_data
                        }
                    elif isinstance(event, dict) and 'event_type' in event:
                        # New dict format from Redis pubsub
                        event_data = event.get('event_data', {})
                        # Handle nested data structure where actual data is in 'data' dict
                        actual_data = event_data.get('data', event_data) if isinstance(event_data, dict) else event_data
                        yield {
                            "event_type": event['event_type'].replace("workflow.", "") if event['event_type'].startswith("workflow.") else event['event_type'],
                            "timestamp": event['timestamp'].isoformat() if hasattr(event['timestamp'], 'isoformat') else datetime.now(UTC).isoformat(),
                            "data": actual_data
                        }
                    else:
                        logger.warning(f"Received unexpected event format: {type(event)}")
                    
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield {
                        "event_type": "heartbeat",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "data": {"task_id": str(task_id)}
                    }
                    continue
                except Exception as e:
                    logger.error(f"Error streaming task events for {task_id}: {e}")
                    break

        finally:
            # Clean up the listener task
            if listener_task and not listener_task.done():
                listener_task.cancel()
                try:
                    await listener_task
                except asyncio.CancelledError:
                    pass

    async def _get_historical_events(self, task_id: UUID) -> List[dict[str, Any]]:
        """Get historical events for a task.

        This could be implemented by:
        1. Querying workflow events via Temporal
        2. Reading from an event store/database
        3. Reconstructing from task state changes
        """
        # Placeholder implementation
        return [
            {
                "event_type": "task_created",
                "task_id": str(task_id),
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {"status": "pending"}
            }
        ]
