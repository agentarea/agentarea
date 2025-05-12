from collections.abc import AsyncGenerator
from uuid import UUID

from google.adk.agents import LlmAgent
from google.adk.models import types
from google.adk.runners import Runner
from google.adk.sessions import SessionService

from agentarea.common.events.broker import EventBroker
from agentarea.modules.llm.application.service import LLMModelInstanceService

from ..infrastructure.repository import AgentRepository


class AgentRunnerService:
    def __init__(
        self,
        repository: AgentRepository,
        event_broker: EventBroker,
        llm_model_instance_service: LLMModelInstanceService,
        session_service: SessionService,
    ):
        self.repository = repository
        self.event_broker = event_broker
        self.llm_model_instance_service = llm_model_instance_service
        self.session_service = session_service

    async def run_agent(
        self, agent_id: UUID, user_id: str, query: str
    ) -> AsyncGenerator[dict, None]:
        # Get the agent
        agent = await self.repository.get(agent_id)
        if not agent:
            raise ValueError(f"Agent with ID {agent_id} not found")

        # Get the LLM model instance
        model_instance = await self.llm_model_instance_service.get(UUID(agent.model_id))
        if not model_instance:
            raise ValueError(f"LLM model instance with ID {agent.model_id} not found")

        # Create or get session
        app_name = f"agent_{agent_id}"
        session = self.session_service.create_session(
            state={}, app_name=app_name, user_id=user_id
        )

        # Configure tools based on agent's tools_config
        tools = []
        if agent.tools_config:
            # Here you would implement logic to load tools based on the configuration
            # For example, if there are MCP server configs:
            if agent.tools_config.get("mcp_server_configs"):
                for mcp_config in agent.tools_config.get("mcp_server_configs", []):
                    # Logic to connect to MCP server and get tools
                    pass

        # Create LLM agent
        llm_agent = LlmAgent(
            model=model_instance,  # You might need to adapt this based on your model interface
            name=agent.name,
            instruction=agent.instruction,
            tools=tools,
            planning=agent.planning,
        )

        # Create runner
        runner = Runner(
            app_name=app_name,
            agent=llm_agent,
            session_service=self.session_service,
        )

        # Create content from query
        content = types.Content(role="user", parts=[types.Part(text=query)])

        # Run the agent and yield events
        response = runner.run_async(
            session_id=session.id,
            user_id=user_id,
            new_message=content,
        )

        async for event in response:
            yield event
