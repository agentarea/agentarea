"""Factory for agent-to-agent tools (one agent invoking another).

Delegation is the concept; A2A is one transport binding of it for remote
targets — not the umbrella. This factory picks the binding by config:
- AgentDelegationTool: same-platform agents (direct task service call, no HTTP)
- A2AAgentTool: external agents (HTTP call via the A2A protocol)
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .a2a_agent_tool import A2AAgentTool
from .agent_delegation_tool import AgentDelegationTool
from .base_tool import BaseTool
from .delegation_tool import DelegationTool

logger = logging.getLogger(__name__)

PaymentHandler = Callable[..., Awaitable[dict[str, Any] | None]]


class AgentToolFactory:
    """Factory for agent-to-agent tool instances (one agent invoking another).

    Delegation is the concept; A2A is one transport binding of it for remote
    targets — not the umbrella. This factory picks the binding:

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
        payment_handler: PaymentHandler | None = None,
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
            payment_handler: Optional HTTP 402 handler for external A2A calls

        Returns:
            BaseTool instance (AgentDelegationTool or A2AAgentTool), or None if agent not found
        """
        try:
            agent = await agent_service.get_by_name(agent_name)
            if not agent:
                logger.warning(f"Agent '{agent_name}' not found for delegation tool creation")
                return None

            description = description_override or agent.description or f"Agent: {agent_name}"

            # Pick the transport binding for this target agent, then wrap it in the
            # single DelegationTool facade. The model always sees one delegate_to_<agent>
            # tool; local-vs-A2A is an execution detail chosen here.

            # Remote agent: an explicit A2A URL forces the A2A binding.
            if a2a_url_override:
                logger.info(f"Delegation '{agent_name}': A2A binding -> {a2a_url_override}")
                binding = A2AAgentTool(
                    agent_name=agent_name,
                    agent_description=description,
                    a2a_url=a2a_url_override,
                    auth_token=auth_token,
                    payment_handler=payment_handler,
                )
                return DelegationTool(binding, "a2a")

            # Same-platform agent: resolved locally and we have execution context →
            # local binding (direct task service, no HTTP/auth overhead).
            if task_service and workspace_id and user_id:
                logger.info(f"Delegation '{agent_name}': local binding (id={agent.id})")
                binding = AgentDelegationTool(
                    agent_name=agent_name,
                    agent_description=description,
                    target_agent_id=agent.id,
                    task_service=task_service,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                return DelegationTool(binding, "local")

            # Fallback: no local execution context → A2A binding against our own endpoint.
            logger.warning(
                f"Delegation '{agent_name}': A2A binding fallback (no task_service). "
                "Pass task_service for same-platform agents to use the local binding."
            )
            a2a_url = f"{base_url}/agents/{agent.id}/a2a/rpc"
            binding = A2AAgentTool(
                agent_name=agent_name,
                agent_description=description,
                a2a_url=a2a_url,
                auth_token=auth_token,
                payment_handler=payment_handler,
            )
            return DelegationTool(binding, "a2a")

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
        payment_handler: PaymentHandler | None = None,
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
            tool = await AgentToolFactory.create_tool(
                agent_name=agent_name,
                agent_service=agent_service,
                base_url=base_url,
                a2a_url_override=settings.get("a2a_url"),
                auth_token=auth_token,
                description_override=settings.get("description_override"),
                task_service=task_service,
                workspace_id=workspace_id,
                user_id=user_id,
                payment_handler=payment_handler,
            )
            if tool:
                tools.append(tool)
                kind = getattr(tool, "binding_kind", "unknown")
                logger.info(f"Created delegation tool ({kind} binding): {tool.name}")

        return tools
