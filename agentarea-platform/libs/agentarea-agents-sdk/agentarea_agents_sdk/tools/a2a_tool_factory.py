"""Factory for creating A2A agent tools from configuration."""

import logging
from typing import Any

from .a2a_agent_tool import A2AAgentTool

logger = logging.getLogger(__name__)


class A2AAgentToolFactory:
    """Factory for creating A2AAgentTool instances.

    Resolves agent names to their A2A endpoint URLs using the agent service,
    then creates tool instances that can call those agents.
    """

    @staticmethod
    async def create_tool(
        agent_name: str,
        agent_service,
        base_url: str,
        a2a_url_override: str | None = None,
        auth_token: str | None = None,
        description_override: str | None = None,
    ) -> A2AAgentTool | None:
        try:
            agent = await agent_service.get_by_name(agent_name)
            if not agent:
                logger.warning(f"Agent '{agent_name}' not found for A2A tool creation")
                return None

            if a2a_url_override:
                a2a_url = a2a_url_override
            else:
                a2a_url = f"{base_url}/agents/{agent.id}/a2a/rpc"

            description = description_override or agent.description or f"Agent: {agent_name}"

            return A2AAgentTool(
                agent_name=agent_name,
                agent_description=description,
                a2a_url=a2a_url,
                auth_token=auth_token,
            )

        except Exception as e:
            logger.error(f"Failed to create A2A tool for agent '{agent_name}': {e}")
            return None

    @staticmethod
    async def create_tools_from_config(
        tools_config: list[dict[str, Any]],
        agent_service,
        base_url: str,
        auth_token: str | None = None,
    ) -> list[A2AAgentTool]:
        tools = []
        for config in tools_config:
            if config.get("type") != "agent":
                continue

            agent_name = config.get("name")
            if not agent_name:
                continue

            settings = config.get("settings") or {}
            tool = await A2AAgentToolFactory.create_tool(
                agent_name=agent_name,
                agent_service=agent_service,
                base_url=base_url,
                a2a_url_override=settings.get("a2a_url"),
                auth_token=auth_token,
                description_override=settings.get("description_override"),
            )
            if tool:
                tools.append(tool)
                logger.info(f"Created A2A agent tool: {tool.name}")

        return tools
