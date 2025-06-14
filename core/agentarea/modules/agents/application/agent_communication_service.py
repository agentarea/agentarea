"""
Agent Communication Service for agent-to-agent interactions via A2A protocol.

This service enables agents to communicate with each other by creating tasks
and retrieving results using the A2A protocol, with Google ADK integration.
"""

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

from google.adk.agents import LlmAgent
from google.adk.tools import Tool, ToolSpec
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

from agentarea.common.events.broker import EventBroker
from agentarea.common.utils.types import (
    Message,
    SendTaskRequest,
    Task,
    TaskSendParams,
    TaskState,
    TextPart,
)
from agentarea.modules.tasks.task_manager import BaseTaskManager

logger = logging.getLogger(__name__)


class AgentCommunicationTool(Tool):
    """Google ADK Tool for agent-to-agent communication."""
    
    def __init__(self, agent_communication_service):
        """Initialize the agent communication tool.
        
        Args:
            agent_communication_service: The AgentCommunicationService instance
        """
        self.agent_communication_service = agent_communication_service
        
        # Define tool specification
        spec = ToolSpec(
            name="ask_agent",
            description="Ask another agent to perform a task and get the result",
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the agent to ask"
                    },
                    "message": {
                        "type": "string",
                        "description": "Message to send to the agent"
                    },
                    "wait_for_response": {
                        "type": "boolean",
                        "description": "Whether to wait for the response or just create the task",
                        "default": True
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Additional metadata for the task",
                        "additionalProperties": True
                    }
                },
                "required": ["agent_id", "message"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the created task"
                    },
                    "status": {
                        "type": "string",
                        "description": "Status of the task"
                    },
                    "response": {
                        "type": "string",
                        "description": "Response from the agent (if wait_for_response is True)"
                    }
                }
            }
        )
        
        super().__init__(spec=spec)
    
    async def execute(self, agent_id: str, message: str, wait_for_response: bool = True, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute the tool by asking another agent to perform a task.
        
        Args:
            agent_id: ID of the agent to ask
            message: Message to send to the agent
            wait_for_response: Whether to wait for the response
            metadata: Additional metadata for the task
            
        Returns:
            Dictionary with task_id, status, and optionally response
        """
        try:
            # Convert string agent_id to UUID
            agent_uuid = UUID(agent_id)
            
            # Create task for the target agent
            task_id, task = await self.agent_communication_service.create_task_for_agent(
                agent_id=agent_uuid,
                message=message,
                metadata=metadata or {}
            )
            
            result = {
                "task_id": task_id,
                "status": task.status.state
            }
            
            # If wait_for_response is True, wait for the task to complete
            if wait_for_response:
                response = await self.agent_communication_service.wait_for_task_completion(task_id)
                result["response"] = response
            
            return result
        
        except Exception as e:
            logger.error(f"Error executing ask_agent tool: {e}", exc_info=True)
            return {
                "task_id": None,
                "status": "failed",
                "error": str(e)
            }


class AgentCommunicationService:
    """Service for agent-to-agent communication using the A2A protocol."""
    
    def __init__(
        self,
        task_manager: BaseTaskManager,
        event_broker: EventBroker,
        enable_agent_communication: bool = True,
        max_wait_time: int = 60,  # Maximum time to wait for task completion in seconds
    ):
        """Initialize the agent communication service.
        
        Args:
            task_manager: Task manager for creating and managing tasks
            event_broker: Event broker for publishing and subscribing to events
            enable_agent_communication: Whether to enable agent-to-agent communication
            max_wait_time: Maximum time to wait for task completion in seconds
        """
        self.task_manager = task_manager
        self.event_broker = event_broker
        self.enable_agent_communication = enable_agent_communication
        self.max_wait_time = max_wait_time
        self.task_completion_events = {}  # Dictionary to store task completion events
        
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
    
    async def create_task_for_agent(
        self,
        agent_id: UUID,
        message: str,
        metadata: Dict[str, Any] = None
    ) -> Tuple[str, Task]:
        """Create a task for another agent using the A2A protocol.
        
        Args:
            agent_id: ID of the agent to create the task for
            message: Message to send to the agent
            metadata: Additional metadata for the task
            
        Returns:
            Tuple of (task_id, task)
            
        Raises:
            ValueError: If agent communication is disabled
        """
        if not self.enable_agent_communication:
            raise ValueError("Agent-to-agent communication is disabled")
        
        # Generate a unique task ID
        task_id = str(uuid.uuid4())
        
        # Create a message from the text
        user_message = Message(
            role="user",
            parts=[TextPart(text=message)]
        )
        
        # Prepare metadata with agent ID
        task_metadata = metadata or {}
        task_metadata["agent_id"] = str(agent_id)
        task_metadata["is_agent_to_agent"] = True
        
        # Create task send parameters
        params = TaskSendParams(
            id=task_id,
            sessionId=str(uuid.uuid4()),
            message=user_message,
            metadata=task_metadata
        )
        
        # Create and send the task using A2A protocol
        request = SendTaskRequest(
            id=str(uuid.uuid4()),
            params=params
        )
        
        # Send the task and get the response
        response = await self.task_manager.on_send_task(request)
        if response.error:
            raise ValueError(f"Failed to create task: {response.error.message}")
        
        # Register the task for completion tracking
        self._register_task_for_completion(task_id)
        
        return task_id, response.result
    
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
            "status": "pending"
        }
    
    async def wait_for_task_completion(self, task_id: str) -> Union[str, Dict[str, Any]]:
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
            # Try to get the task from the task manager
            request = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tasks/get",
                "params": {"id": task_id}
            }
            
            # Get the task
            response = await self.task_manager.on_get_task(request)
            if response.error:
                raise ValueError(f"Task {task_id} not found")
            
            # Check if the task is already completed
            task = response.result
            if task.status.state in [TaskState.COMPLETED, TaskState.FAILED]:
                # Extract the result or error message
                if task.status.state == TaskState.COMPLETED:
                    # Try to extract the result from the task
                    if task.artifacts and len(task.artifacts) > 0:
                        # Return the text from the first artifact
                        for artifact in task.artifacts:
                            for part in artifact.parts:
                                if hasattr(part, "text") and part.text:
                                    return part.text
                    
                    # If no artifacts with text, return the last message
                    if task.history and len(task.history) > 0:
                        for message in reversed(task.history):
                            if message.role == "agent":
                                for part in message.parts:
                                    if hasattr(part, "text") and part.text:
                                        return part.text
                    
                    # If no result found, return a generic message
                    return "Task completed successfully but no result found"
                else:
                    return {"error": "Task failed", "task_id": task_id}
            
            # If the task is still in progress, register it for tracking
            self._register_task_for_completion(task_id)
        
        # Get the completion event
        completion_data = self.task_completion_events.get(task_id)
        if not completion_data:
            raise ValueError(f"Task {task_id} not found in completion tracking")
        
        # Wait for the event with timeout
        try:
            await asyncio.wait_for(completion_data["event"].wait(), timeout=self.max_wait_time)
        except asyncio.TimeoutError:
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
                return result
            
            # Try to extract text content
            if "text" in result:
                return result["text"]
            elif "content" in result:
                return result["content"]
        
        # Return the raw result if we couldn't extract text
        return result or "Task completed but no result available"
    
    def get_agent_communication_tool(self) -> Optional[Tool]:
        """Get the agent communication tool for use with Google ADK.
        
        Returns:
            Tool for agent communication or None if communication is disabled
        """
        if not self.enable_agent_communication:
            return None
        
        return AgentCommunicationTool(self)
    
    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get the status of a task.
        
        Args:
            task_id: ID of the task to check
            
        Returns:
            Dictionary with task status information
            
        Raises:
            ValueError: If the task is not found
        """
        # Create a request to get the task
        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/get",
            "params": {"id": task_id}
        }
        
        # Get the task
        response = await self.task_manager.on_get_task(request)
        if response.error:
            raise ValueError(f"Task {task_id} not found")
        
        # Extract the task status
        task = response.result
        status_info = {
            "task_id": task.id,
            "status": task.status.state,
            "timestamp": task.status.timestamp.isoformat() if hasattr(task.status, "timestamp") else None
        }
        
        # Add additional information if available
        if task.metadata:
            status_info["metadata"] = task.metadata
        
        return status_info
    
    def configure_agent_with_communication(
        self,
        llm_agent: LlmAgent,
        enable_communication: bool = None
    ) -> LlmAgent:
        """Configure an LlmAgent with agent communication capabilities.
        
        Args:
            llm_agent: The LlmAgent to configure
            enable_communication: Override the global enable_agent_communication setting
            
        Returns:
            The configured LlmAgent
        """
        # Determine whether to enable communication
        should_enable = enable_communication if enable_communication is not None else self.enable_agent_communication
        
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
