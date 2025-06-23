"""A2A Server Implementation.

This module implements an A2A server using the official Google A2A SDK,
allowing our agents to be discoverable and callable by other A2A-compliant systems.
"""

import logging
from uuid import UUID

# A2A SDK imports
from a2a.sdk import A2AServer, AgentCard, Capability, TaskRequest, TaskResponse
from a2a.sdk.types import Artifact, TextPart

from agentarea.modules.agents.application.agent_runner_service import AgentRunnerService
from agentarea.modules.agents.application.agent_service import AgentService

logger = logging.getLogger(__name__)


class AgentAreaA2AServer:
    """A2A Server implementation for AgentArea agents.

    This allows external A2A systems to discover and interact with our agents
    following the official A2A protocol specification.
    """

    def __init__(
        self,
        agent_service: AgentService,
        agent_runner_service: AgentRunnerService,
        server_host: str = "0.0.0.0",
        server_port: int = 8001,
    ):
        self.agent_service = agent_service
        self.agent_runner_service = agent_runner_service
        self.server_host = server_host
        self.server_port = server_port
        self.a2a_server: A2AServer | None = None

    async def start_server(self):
        """Start the A2A server."""
        try:
            # Create A2A server instance
            self.a2a_server = A2AServer(
                host=self.server_host,
                port=self.server_port,
                task_handler=self._handle_task,
                agent_card_provider=self._get_agent_card,
            )

            await self.a2a_server.start()
            logger.info(f"A2A server started on {self.server_host}:{self.server_port}")

        except Exception as e:
            logger.error(f"Failed to start A2A server: {e}", exc_info=True)
            raise

    async def stop_server(self):
        """Stop the A2A server."""
        if self.a2a_server:
            await self.a2a_server.stop()
            logger.info("A2A server stopped")

    async def _handle_task(self, task_request: TaskRequest) -> TaskResponse:
        """Handle incoming A2A task requests.

        Args:
            task_request: A2A task request from external system

        Returns:
            A2A task response with results
        """
        try:
            # Extract agent ID from task metadata or routing
            agent_id_str = task_request.metadata.get("agent_id")
            if not agent_id_str:
                # Default to first available agent or use routing logic
                agents = await self.agent_service.list()
                if not agents:
                    return TaskResponse(
                        task_id=task_request.id, status="failed", error="No agents available"
                    )
                agent_id_str = str(agents[0].id)

            try:
                agent_id = UUID(agent_id_str)
            except ValueError:
                return TaskResponse(
                    task_id=task_request.id,
                    status="failed",
                    error=f"Invalid agent ID: {agent_id_str}",
                )

            # Extract message content
            message_text = ""
            if task_request.message and task_request.message.parts:
                for part in task_request.message.parts:
                    if isinstance(part, TextPart):
                        message_text += part.text

            if not message_text:
                return TaskResponse(
                    task_id=task_request.id, status="failed", error="No message content provided"
                )

            # Execute task using our agent runner
            results = []
            async for event in self.agent_runner_service.run_agent_task(
                agent_id=agent_id,
                task_id=task_request.id,
                user_id=task_request.metadata.get("user_id", "a2a_external"),
                query=message_text,
                task_parameters=task_request.metadata,
            ):
                results.append(event)

                # If this is a completion event, extract the result
                if event.get("event_type") == "TaskCompleted":
                    result_content = ""
                    if "result" in event and isinstance(event["result"], dict):
                        result_content = event["result"].get(
                            "content", "Task completed successfully"
                        )
                    elif "original_event" in event:
                        # Extract content from ADK event
                        orig_event = event["original_event"]
                        if hasattr(orig_event, "text"):
                            result_content = orig_event.text
                        elif hasattr(orig_event, "content"):
                            result_content = str(orig_event.content)
                        else:
                            result_content = "Task completed successfully"

                    # Create A2A response
                    return TaskResponse(
                        task_id=task_request.id,
                        status="completed",
                        artifacts=[
                            Artifact(
                                type="text",
                                content=result_content,
                                metadata={"source": "agentarea", "agent_id": str(agent_id)},
                            )
                        ],
                        metadata={
                            "execution_events": len(results),
                            "agent_id": str(agent_id),
                            "processed_by": "agentarea",
                        },
                    )

            # If we get here, the task didn't complete properly
            return TaskResponse(
                task_id=task_request.id,
                status="failed",
                error="Task execution completed without result",
            )

        except Exception as e:
            logger.error(f"Error handling A2A task {task_request.id}: {e}", exc_info=True)
            return TaskResponse(
                task_id=task_request.id, status="failed", error=f"Internal error: {str(e)}"
            )

    async def _get_agent_card(self, agent_id: str | None = None) -> AgentCard:
        """Provide agent card for A2A discovery.

        Args:
            agent_id: Optional specific agent ID

        Returns:
            A2A AgentCard for discovery
        """
        try:
            if agent_id:
                # Get specific agent
                try:
                    agent_uuid = UUID(agent_id)
                    agent = await self.agent_service.get(agent_uuid)
                    if not agent:
                        # Return default card if agent not found
                        return self._create_default_agent_card()

                    return AgentCard(
                        id=str(agent.id),
                        name=agent.name,
                        description=agent.description or "AgentArea agent",
                        capabilities=[
                            Capability(
                                name="chat",
                                description="Chat and conversation capabilities",
                                input_modes=["text"],
                                output_modes=["text"],
                            ),
                            Capability(
                                name="task_execution",
                                description="Execute complex tasks and workflows",
                                input_modes=["text"],
                                output_modes=["text", "artifacts"],
                            ),
                        ],
                        metadata={
                            "platform": "agentarea",
                            "protocol_version": "1.0",
                            "model": "configurable",
                            "features": ["streaming", "artifacts", "memory"],
                        },
                    )
                except ValueError:
                    # Invalid UUID, return default
                    return self._create_default_agent_card()
            else:
                # Return platform-level card
                return self._create_default_agent_card()

        except Exception as e:
            logger.error(f"Error creating agent card: {e}", exc_info=True)
            return self._create_default_agent_card()

    def _create_default_agent_card(self) -> AgentCard:
        """Create a default agent card for the platform."""
        return AgentCard(
            id="agentarea-platform",
            name="AgentArea Platform",
            description="AgentArea multi-agent platform with configurable agents",
            capabilities=[
                Capability(
                    name="multi_agent",
                    description="Multiple specialized agents with different capabilities",
                    input_modes=["text"],
                    output_modes=["text", "artifacts"],
                ),
                Capability(
                    name="agent_communication",
                    description="Agent-to-agent communication and coordination",
                    input_modes=["text"],
                    output_modes=["text"],
                ),
            ],
            metadata={
                "platform": "agentarea",
                "protocol_version": "1.0",
                "agent_count": "multiple",
                "features": ["multi_agent", "streaming", "artifacts", "memory", "tools"],
            },
        )


class A2AServerManager:
    """Manager for A2A server lifecycle."""

    def __init__(self):
        self.server: AgentAreaA2AServer | None = None
        self._running = False

    async def start(
        self,
        agent_service: AgentService,
        agent_runner_service: AgentRunnerService,
        host: str = "0.0.0.0",
        port: int = 8001,
    ):
        """Start the A2A server."""
        if self._running:
            logger.warning("A2A server is already running")
            return

        self.server = AgentAreaA2AServer(
            agent_service=agent_service,
            agent_runner_service=agent_runner_service,
            server_host=host,
            server_port=port,
        )

        await self.server.start_server()
        self._running = True

    async def stop(self):
        """Stop the A2A server."""
        if self.server and self._running:
            await self.server.stop_server()
            self._running = False

    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running


# Global server manager instance
a2a_server_manager = A2AServerManager()
