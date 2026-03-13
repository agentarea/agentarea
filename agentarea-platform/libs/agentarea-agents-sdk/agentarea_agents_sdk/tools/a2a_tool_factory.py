"""Factory for creating agent delegation tools from configuration.

Creates the appropriate tool type:
- AgentDelegationTool: for same-platform agents (direct task service call, no HTTP)
- A2AAgentTool: for external agents (HTTP call via A2A protocol)
"""

import logging
from typing import Any

from .a2a_agent_tool import A2AAgentTool
from .agent_delegation_tool import AgentDelegationTool
from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class A2AAgentToolFactory:
    """Factory for creating agent delegation tool instances.

    For same-platform agents (no explicit a2a_url), creates AgentDelegationTool
    which calls the task service directly — no HTTP, no auth overhead.

    For external agents (explicit a2a_url in settings), creates A2AAgentTool
    which makes HTTP calls via the A2A protocol.
    """

    @staticmethod
    async def create_tool(
        agent_name: str,
        agent_service,
        base_url: str,
        a2a_url_override: str | None = None,
        auth_token: str | None = None,
        description_override: str | None = None,
        task_service=None,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> BaseTool | None:
        """Create a delegation tool for a given agent.

        Args:
            agent_name: Name of the target agent
            agent_service: AgentService to look up agent details
            base_url: Base API URL (used for external A2A fallback)
            a2a_url_override: Explicit A2A URL → creates external A2AAgentTool
            auth_token: Bearer token for external A2A calls
            description_override: Override agent description in tool schema
            task_service: TaskService for internal delegation
            workspace_id: Workspace context for internal delegation
            user_id: User context for internal delegation

        Returns:
            BaseTool instance (AgentDelegationTool or A2AAgentTool), or None if agent not found
        """
        try:
            agent = await agent_service.get_by_name(agent_name)
            if not agent:
                logger.warning(f"Agent '{agent_name}' not found for delegation tool creation")
                return None

            description = description_override or agent.description or f"Agent: {agent_name}"

            # External agent: explicit A2A URL provided
            if a2a_url_override:
                logger.info(f"Creating external A2A tool for '{agent_name}' -> {a2a_url_override}")
                return A2AAgentTool(
                    agent_name=agent_name,
                    agent_description=description,
                    a2a_url=a2a_url_override,
                    auth_token=auth_token,
                )

            # Internal agent: use task service directly (no HTTP)
            if task_service and workspace_id and user_id:
                logger.info(f"Creating delegation tool for '{agent_name}' (id={agent.id})")
                return AgentDelegationTool(
                    agent_name=agent_name,
                    agent_description=description,
                    target_agent_id=agent.id,
                    task_service=task_service,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )

            # Fallback: external A2A (less ideal — needs auth token to work)
            logger.warning(
                f"Creating external A2A tool for '{agent_name}' (no task_service provided). "
                "Internal delegation preferred — pass task_service for same-platform agents."
            )
            a2a_url = f"{base_url}/agents/{agent.id}/a2a/rpc"
            return A2AAgentTool(
                agent_name=agent_name,
                agent_description=description,
                a2a_url=a2a_url,
                auth_token=auth_token,
            )

        except Exception as e:
            logger.error(f"Failed to create delegation tool for agent '{agent_name}': {e}")
            return None

    @staticmethod
    async def create_tools_from_config(
        tools_config: list[dict[str, Any]],
        agent_service,
        base_url: str,
        auth_token: str | None = None,
        task_service=None,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> list[BaseTool]:
        """Create delegation tools from agent tool configs."""
        tools: list[BaseTool] = []
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
                task_service=task_service,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            if tool:
                tools.append(tool)
                tool_type = "internal" if isinstance(tool, AgentDelegationTool) else "external/a2a"
                logger.info(f"Created {tool_type} agent tool: {tool.name}")

        return tools
