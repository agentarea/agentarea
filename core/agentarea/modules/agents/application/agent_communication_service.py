"""Agent Communication Service for agent-to-agent interactions via A2A protocol.

This service enables agents to communicate with each other by creating tasks
and retrieving results using the A2A protocol, with Google ADK integration.
"""

import asyncio
import logging
import uuid
from typing import Any, TYPE_CHECKING
from uuid import UUID

from google.adk.agents import LlmAgent
from google.adk.tools.function_tool import FunctionTool

from agentarea.common.events.broker import EventBroker

# Avoid circular imports
if TYPE_CHECKING:
    from .agent_runner_service import AgentRunnerService

logger = logging.getLogger(__name__)


def create_agent_communication_function(agent_communication_service: "AgentCommunicationService"):
    """Create the agent communication function that will be wrapped as a FunctionTool.

    Args:
        agent_communication_service: The AgentCommunicationService instance

    Returns:
        The agent communication function
    """

    async def ask_agent(
        agent_id: str,
        message: str,
        wait_for_response: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ask another agent to perform a task and get the result.

        Args:
            agent_id: ID of the agent to ask
            message: Message to send to the agent
            wait_for_response: Whether to wait for the response or just create the task
            metadata: Additional metadata for the task

        Returns:
            Dictionary containing:
            - task_id: ID of the created task
            - status: Status of the task
            - response: Response from the agent (if wait_for_response is True)
        """
        try:
            # Convert string agent_id to UUID
            agent_uuid = UUID(agent_id)

            # Create task for the target agent using the proper execution flow
            task_id, result = await agent_communication_service.execute_agent_task(
                agent_id=agent_uuid,
                message=message,
                wait_for_response=wait_for_response,
                metadata=metadata or {},
            )

            return {
                "task_id": task_id,
                "status": "completed" if result else "created",
                "response": result if wait_for_response else None,
            }

        except Exception as e:
            logger.error(f"Error executing ask_agent tool: {e}", exc_info=True)
            return {"task_id": None, "status": "failed", "error": str(e)}

    return ask_agent


class AgentCommunicationService:
    """Service for agent-to-agent communication using proper agent execution flow."""

    def __init__(
        self,
        agent_runner_service: "AgentRunnerService",
        event_broker: EventBroker,
        enable_agent_communication: bool = True,
        max_wait_time: int = 60,  # Maximum time to wait for task completion in seconds
    ):
        """Initialize the agent communication service.

        Args:
            agent_runner_service: AgentRunnerService for executing tasks
            event_broker: Event broker for publishing and subscribing to events
            enable_agent_communication: Whether to enable agent-to-agent communication
            max_wait_time: Maximum time to wait for task completion in seconds
        """
        self.agent_runner_service = agent_runner_service
        self.event_broker = event_broker
        self.enable_agent_communication = enable_agent_communication
        self.max_wait_time = max_wait_time
        self.task_completion_events: dict[
            str, dict[str, Any]
        ] = {}  # Dictionary to store task completion events

        # Initialize task completion tracking
        self._initialize_task_tracking()

    def _initialize_task_tracking(self):
        """Initialize task completion tracking."""
        if not self.enable_agent_communication:
            logger.info("Agent-to-agent communication is disabled")
            return

        # Set up event listeners for task completion
        asyncio.create_task(self._setup_task_completion_listeners())

    async def _setup_task_completion_listeners(self):
        """Set up event listeners for task completion events."""
        try:
            # Subscribe to task completion events
            await self.event_broker.subscribe("TaskCompleted", self._handle_task_completed)
            await self.event_broker.subscribe("TaskFailed", self._handle_task_failed)
            logger.info("Task completion listeners set up successfully")
        except Exception as e:
            logger.error(f"Error setting up task completion listeners: {e}", exc_info=True)

    async def _handle_task_completed(self, event):
        """Handle task completed events."""
        task_id = event.data.get("task_id")
        if not task_id or task_id not in self.task_completion_events:
            return

        # Get the event and set it to notify waiters
        completion_event = self.task_completion_events.get(task_id)
        if completion_event:
            # Set result to the task data
            completion_event["result"] = event.data.get("result", {})
            completion_event["status"] = "completed"
            # Set the event to notify waiters
            completion_event["event"].set()

    async def _handle_task_failed(self, event):
        """Handle task failed events."""
        task_id = event.data.get("task_id")
        if not task_id or task_id not in self.task_completion_events:
            return

        # Get the event and set it to notify waiters
        completion_event = self.task_completion_events.get(task_id)
        if completion_event:
            # Set error to the task data
            completion_event["result"] = {"error": event.data.get("error_message", "Unknown error")}
            completion_event["status"] = "failed"
            # Set the event to notify waiters
            completion_event["event"].set()

    async def execute_agent_task(
        self,
        agent_id: UUID,
        message: str,
        wait_for_response: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, str | None]:
        """Execute a task on another agent using the proper agent execution flow.

        Args:
            agent_id: ID of the agent to execute the task
            message: Message/query to send to the agent
            wait_for_response: Whether to wait for the response
            metadata: Additional metadata for the task

        Returns:
            Tuple of (task_id, response) where response is None if not waiting

        Raises:
            ValueError: If agent communication is disabled
        """
        if not self.enable_agent_communication:
            raise ValueError("Agent-to-agent communication is disabled")

        # Generate a unique task ID
        task_id = str(uuid.uuid4())

        # Prepare metadata with agent communication flag
        task_metadata = metadata or {}
        task_metadata["is_agent_to_agent"] = True
        task_metadata["source_communication_service"] = True

        logger.info(f"Starting agent-to-agent task {task_id} for agent {agent_id}")

        # Register the task for completion tracking if waiting for response
        if wait_for_response:
            self._register_task_for_completion(task_id)

        # Execute the task using AgentRunnerService
        try:
            # Start the task execution in the background
            task_execution = asyncio.create_task(
                self._execute_task_with_events(
                    agent_id=agent_id, task_id=task_id, message=message, metadata=task_metadata
                )
            )

            # If not waiting for response, return immediately
            if not wait_for_response:
                return task_id, None

            # Wait for task completion
            response = await self.wait_for_task_completion(task_id)
            return task_id, response

        except Exception as e:
            logger.error(f"Error executing agent task {task_id}: {e}", exc_info=True)
            # Clean up completion tracking
            self.task_completion_events.pop(task_id, None)
            raise

    async def _execute_task_with_events(
        self, agent_id: UUID, task_id: str, message: str, metadata: dict[str, Any]
    ):
        """Execute the task and handle events internally."""
        try:
            # Use AgentRunnerService to execute the task properly
            async for event in self.agent_runner_service.run_agent_task(
                agent_id=agent_id,
                task_id=task_id,
                user_id=metadata.get("user_id", "a2a_communication"),
                query=message,
                task_parameters=metadata,
                enable_agent_communication=False,  # Prevent recursive A2A calls
            ):
                # Log the event for debugging
                logger.debug(f"A2A task {task_id} event: {event.get('event_type', 'Unknown')}")

                # The events will be handled by our event listeners automatically
                # since AgentRunnerService publishes them to the event broker

        except Exception as e:
            logger.error(f"Error in task execution for A2A task {task_id}: {e}", exc_info=True)

    def _register_task_for_completion(self, task_id: str):
        """Register a task for completion tracking.

        Args:
            task_id: ID of the task to track
        """
        if not self.enable_agent_communication:
            return

        # Create an asyncio event for task completion
        self.task_completion_events[task_id] = {
            "event": asyncio.Event(),
            "result": None,
            "status": "pending",
        }

    async def wait_for_task_completion(self, task_id: str) -> str:
        """Wait for a task to complete and return the result.

        Args:
            task_id: ID of the task to wait for

        Returns:
            Task result or error message

        Raises:
            ValueError: If agent communication is disabled or task not found
            TimeoutError: If the task does not complete within the maximum wait time
        """
        if not self.enable_agent_communication:
            raise ValueError("Agent-to-agent communication is disabled")

        # Check if the task is being tracked
        if task_id not in self.task_completion_events:
            raise ValueError(f"Task {task_id} not found in completion tracking")

        # Get the completion event
        completion_data = self.task_completion_events.get(task_id)
        if not completion_data:
            raise ValueError(f"Task {task_id} not found in completion tracking")

        # Wait for the event with timeout
        try:
            await asyncio.wait_for(completion_data["event"].wait(), timeout=self.max_wait_time)
        except TimeoutError:
            # Remove the task from tracking
            self.task_completion_events.pop(task_id, None)
            raise TimeoutError(f"Timed out waiting for task {task_id} to complete")

        # Get the result
        result = completion_data.get("result")

        # Clean up
        self.task_completion_events.pop(task_id, None)

        # Extract text from result if possible
        if isinstance(result, dict):
            if "error" in result:
                return f"Task failed: {result['error']}"

            # Try to extract text content
            if "text" in result:
                return result["text"]
            elif "content" in result:
                return result["content"]

        # Return the raw result if we couldn't extract text
        return str(result) if result else "Task completed but no result available"

    def get_agent_communication_tool(self) -> FunctionTool | None:
        """Get the agent communication tool for use with Google ADK.

        Returns:
            FunctionTool for agent communication or None if communication is disabled
        """
        if not self.enable_agent_communication:
            return None

        # Create the function and wrap it in a FunctionTool
        ask_agent_func = create_agent_communication_function(self)
        return FunctionTool(func=ask_agent_func)

    def configure_agent_with_communication(
        self, llm_agent: LlmAgent, enable_communication: bool | None = None
    ) -> LlmAgent:
        """Configure an LlmAgent with agent communication capabilities.

        Args:
            llm_agent: The LlmAgent to configure
            enable_communication: Override the global enable_agent_communication setting

        Returns:
            The configured LlmAgent
        """
        # Determine whether to enable communication
        should_enable = (
            enable_communication
            if enable_communication is not None
            else self.enable_agent_communication
        )

        if not should_enable:
            logger.info("Agent-to-agent communication is disabled for this agent")
            return llm_agent

        # Get the agent communication tool
        communication_tool = self.get_agent_communication_tool()

        # Add the tool to the agent's tools
        if communication_tool:
            # Create a new list with existing tools plus the communication tool
            tools = list(llm_agent.tools) if llm_agent.tools else []
            tools.append(communication_tool)

            # Update the agent's tools
            llm_agent.tools = tools

            logger.info("Agent configured with agent-to-agent communication capability")

        return llm_agent
