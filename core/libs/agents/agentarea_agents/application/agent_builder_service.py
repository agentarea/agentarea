"""Agent Builder Service for composing agents from database data."""

import logging
from typing import Any, cast
from uuid import UUID

from agentarea_common.events.broker import EventBroker
from agentarea_common.utils.types import sanitize_agent_name
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.domain.models import ModelInstance
from agentarea_mcp.application.service import MCPServerInstanceService

from agentarea_agents.domain.models import Agent
from agentarea_agents.infrastructure.repository import AgentRepository

logger = logging.getLogger(__name__)


class AgentBuilderService:
    """Service responsible for composing agent configurations from various data sources."""

    def __init__(
        self,
        repository: AgentRepository,
        event_broker: EventBroker,
        model_instance_service: ModelInstanceService,
        mcp_server_instance_service: MCPServerInstanceService | None = None,
    ):
        self.repository = repository
        self.event_broker = event_broker
        self.model_instance_service = model_instance_service
        self.mcp_server_instance_service = mcp_server_instance_service

    async def build_agent_config(self, agent_id: UUID) -> dict[str, Any] | None:
        """Build a complete agent configuration from database data.

        Args:
            agent_id: The UUID of the agent to build

        Returns:
            Complete agent configuration dict or None if agent not found
        """
        # Get the agent from database
        agent = await self.repository.get(agent_id)
        if not agent:
            logger.error(f"Agent with ID {agent_id} not found")
            return None

        # Get model instance using new 4-entity architecture
        model_instance: ModelInstance | None = None
        if agent.model_id:
            try:
                model_instance = await self.model_instance_service.get(UUID(agent.model_id))
                if model_instance:
                    logger.info(f"Using ModelInstance for agent {agent_id}")
            except (ValueError, TypeError) as e:
                logger.error(
                    f"Invalid model_id format for agent {agent_id}: {agent.model_id}, error: {e}"
                )

        if not model_instance:
            logger.error(
                f"Model instance not found for agent {agent_id}, model_id: {agent.model_id}"
            )
            return None

        # Build tools configuration
        tools_config = await self._build_tools_config(agent)

        # Build complete agent configuration
        agent_config: dict[str, Any] = {
            "id": str(agent.id),
            "name": sanitize_agent_name(agent.name),  # Sanitize name for Google ADK
            "description": agent.description,
            "instruction": agent.instruction,
            "model_instance": model_instance,
            "tools_config": tools_config,
            "events_config": agent.events_config or {},  # type: ignore
            # Planning is handled at the workflow level, not LlmAgent level
            # According to ADK docs, planning is achieved using SequentialAgent, ParallelAgent, etc.
            "planning_enabled": agent.planning or False,  # Renamed for clarity
            "workflow_type": "sequential" if agent.planning else "single",  # Workflow planning
            "status": agent.status,
            "metadata": {
                "created_at": agent.created_at.isoformat() if agent.created_at else None,
                "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
            },
        }

        logger.info(
            f"Built agent configuration for {agent.name} -> {sanitize_agent_name(agent.name)} (ID: {agent_id})"
        )
        return agent_config

    async def _build_tools_config(self, agent: Agent) -> dict[str, Any]:
        """Build tools configuration for an agent.

        Args:
            agent: The agent domain model

        Returns:
            Complete tools configuration
        """
        tools_config: dict[str, list[Any]] = {
            "mcp_servers": [],
            "builtin_tools": [],
            "custom_tools": [],
        }

        # Check if agent has tools_config
        agent_tools_config = cast(dict[str, Any], agent.tools_config) if agent.tools_config else {}
        if not agent_tools_config:
            return tools_config

        # Handle MCP server configurations
        mcp_server_configs = agent_tools_config.get("mcp_server_configs", [])
        if mcp_server_configs and self.mcp_server_instance_service:
            for mcp_config in mcp_server_configs:
                try:
                    if isinstance(mcp_config, dict):
                        mcp_server_id = mcp_config.get("mcp_server_id")
                        if mcp_server_id:
                            # Get MCP server instance details
                            mcp_instance = await self.mcp_server_instance_service.get(
                                UUID(str(mcp_server_id))
                            )
                            if mcp_instance:
                                tools_config["mcp_servers"].append(
                                    {
                                        "instance_id": str(mcp_instance.id),
                                        "name": mcp_instance.name,
                                        "endpoint_url": mcp_instance.endpoint_url,
                                        "config": mcp_instance.config,  # type: ignore
                                        "requires_user_confirmation": mcp_config.get(
                                            "requires_user_confirmation", False
                                        ),
                                        "agent_config": mcp_config.get("config", {}),
                                    }
                                )
                            else:
                                logger.warning(
                                    f"MCP server instance {mcp_server_id} not found for agent {agent.id}"
                                )
                except (ValueError, TypeError) as e:
                    logger.error(f"Invalid MCP server config for agent {agent.id}: {e}")

        # Handle builtin tools
        builtin_tools = agent_tools_config.get("builtin_tools", [])
        if builtin_tools:
            tools_config["builtin_tools"] = builtin_tools

        # Handle custom tools
        custom_tools = agent_tools_config.get("custom_tools", [])
        if custom_tools:
            tools_config["custom_tools"] = custom_tools

        return tools_config

    async def validate_agent_config(self, agent_id: UUID) -> list[str]:
        """Validate agent configuration and return list of validation errors.

        Args:
            agent_id: The UUID of the agent to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors: list[str] = []

        # Get the agent
        agent = await self.repository.get(agent_id)
        if not agent:
            errors.append(f"Agent with ID {agent_id} not found")
            return errors

        # Validate required fields
        if not agent.name:
            errors.append("Agent name is required")

        if not agent.instruction:
            errors.append("Agent instruction is required")

        if not agent.model_id:
            errors.append("Agent model_id is required")
        else:
            # Validate model instance exists
            try:
                model_instance = await self.model_instance_service.get(UUID(agent.model_id))
                if not model_instance:
                    errors.append(f"Model instance {agent.model_id} not found")
            except (ValueError, TypeError):
                errors.append(f"Invalid model_id format: {agent.model_id}")

        # Validate tools configuration
        agent_tools_config = cast(dict[str, Any], agent.tools_config) if agent.tools_config else {}
        if agent_tools_config:
            mcp_configs = agent_tools_config.get("mcp_server_configs", [])
            for i, mcp_config in enumerate(mcp_configs):
                if not isinstance(mcp_config, dict):
                    errors.append(f"MCP server config {i} must be a dictionary")
                    continue

                mcp_server_id = mcp_config.get("mcp_server_id")
                if not mcp_server_id:
                    errors.append(f"MCP server config {i} missing mcp_server_id")
                elif self.mcp_server_instance_service:
                    try:
                        mcp_instance = await self.mcp_server_instance_service.get(
                            UUID(str(mcp_server_id))
                        )
                        if not mcp_instance:
                            errors.append(f"MCP server instance {mcp_server_id} not found")
                    except (ValueError, TypeError):
                        errors.append(
                            f"Invalid MCP server ID format in config {i}: {mcp_server_id}"
                        )

        return errors

    async def get_agent_capabilities(self, agent_id: UUID) -> dict[str, Any]:
        """Get agent capabilities based on its configuration.

        Args:
            agent_id: The UUID of the agent

        Returns:
            Dictionary of agent capabilities
        """
        agent_config = await self.build_agent_config(agent_id)
        if not agent_config:
            return {}

        capabilities: dict[str, Any] = {
            "streaming": True,  # All agents support streaming by default
            "planning": agent_config.get("planning_enabled", False),  # Updated field name
            "workflow_type": agent_config.get("workflow_type", "single"),  # Workflow capability
            "tools": {
                "mcp_servers": len(agent_config.get("tools_config", {}).get("mcp_servers", [])),
                "builtin_tools": len(agent_config.get("tools_config", {}).get("builtin_tools", [])),
                "custom_tools": len(agent_config.get("tools_config", {}).get("custom_tools", [])),
            },
            "events": bool(agent_config.get("events_config")),
            "model_provider": getattr(agent_config.get("model_instance"), "provider", "unknown"),
            # ADK-specific capabilities
            "supports_multi_agent": True,  # ADK supports multi-agent systems
            "supports_workflows": True,  # Supports SequentialAgent, ParallelAgent, LoopAgent
            "supports_delegation": True,  # Supports LLM-driven delegation
        }

        return capabilities
