"""Agent handoff tool for multi-agent coordination."""

import json
import logging
from typing import Any

from .base_tool import BaseTool, ToolExecutionError

logger = logging.getLogger(__name__)


class AgentHandoffTool(BaseTool):
    """Tool for handing off tasks to another agent in the multi-agent system."""

    def __init__(
        self,
        available_agents: dict[str, dict[str, Any]] | None = None,
        handoff_callback=None,
    ):
        """Initialize the handoff tool.

        Args:
            available_agents: Dict mapping agent_id to agent metadata (name, description, capabilities)
            handoff_callback: Async callback function to execute the handoff
        """
        self.available_agents = available_agents or {}
        self.handoff_callback = handoff_callback

    @property
    def name(self) -> str:
        return "handoff_to_agent"

    @property
    def description(self) -> str:
        return "Hand off the current task to another specialized agent better suited to handle it"

    def get_schema(self) -> dict[str, Any]:
        """Get the OpenAI function schema for agent handoff."""
        agent_options = []
        for agent_id, metadata in self.available_agents.items():
            agent_options.append(
                {
                    "id": agent_id,
                    "name": metadata.get("name", agent_id),
                    "description": metadata.get("description", ""),
                    "capabilities": metadata.get("capabilities", []),
                }
            )

        return {
            "parameters": {
                "type": "object",
                "properties": {
                    "target_agent_id": {
                        "type": "string",
                        "description": f"ID of the target agent to hand off to. Available agents: {json.dumps(agent_options, indent=2)}",
                        "enum": list(self.available_agents.keys()) if self.available_agents else [],
                    },
                    "handoff_reason": {
                        "type": "string",
                        "description": "Explanation of why this agent is better suited for the task",
                    },
                    "task_context": {
                        "type": "string",
                        "description": "Current task context and any relevant information to pass to the target agent",
                    },
                    "priority": {
                        "type": "string",
                        "description": "Task priority level",
                        "enum": ["low", "medium", "high", "urgent"],
                        "default": "medium",
                    },
                    "expected_deliverable": {
                        "type": "string",
                        "description": "What the target agent should deliver or accomplish",
                    },
                },
                "required": ["target_agent_id", "handoff_reason", "task_context"],
            }
        }

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the agent handoff.

        Args:
            target_agent_id: ID of the target agent
            handoff_reason: Reason for handoff
            task_context: Context to pass to target agent
            priority: Task priority level
            expected_deliverable: What the target agent should accomplish

        Returns:
            Dict containing handoff execution results
        """
        try:
            target_agent_id = kwargs.get("target_agent_id")
            handoff_reason = kwargs.get("handoff_reason", "")
            task_context = kwargs.get("task_context", "")
            priority = kwargs.get("priority", "medium")
            expected_deliverable = kwargs.get("expected_deliverable", "")

            if not target_agent_id:
                raise ToolExecutionError(self.name, "target_agent_id is required for handoff")

            if target_agent_id not in self.available_agents:
                raise ToolExecutionError(
                    self.name, f"Target agent {target_agent_id} not found in available agents"
                )

            # Prepare handoff payload
            handoff_payload = {
                "source_agent": "current",  # This would be set by the calling agent
                "target_agent_id": target_agent_id,
                "target_agent_info": self.available_agents[target_agent_id],
                "handoff_reason": handoff_reason,
                "task_context": task_context,
                "priority": priority,
                "expected_deliverable": expected_deliverable,
                "timestamp": None,  # Would be set during actual handoff
            }

            # Execute handoff if callback is provided
            handoff_result = None
            if self.handoff_callback:
                handoff_result = await self.handoff_callback(handoff_payload)

            logger.info(f"Agent handoff initiated to {target_agent_id}: {handoff_reason}")

            return {
                "success": True,
                "result": {
                    "handoff_initiated": True,
                    "target_agent": self.available_agents[target_agent_id]["name"],
                    "target_agent_id": target_agent_id,
                    "handoff_reason": handoff_reason,
                    "task_context": task_context,
                    "handoff_result": handoff_result,
                },
                "error": None,
                "tool_name": self.name,
                "message": f"Task handed off to {self.available_agents[target_agent_id]['name']} agent",
            }

        except Exception as e:
            logger.error(f"Agent handoff failed: {str(e)}")
            raise ToolExecutionError(self.name, str(e), e) from e


class AgentRegistryTool(BaseTool):
    """Tool for discovering available agents in the system."""

    def __init__(self, available_agents: dict[str, dict[str, Any]] | None = None):
        """Initialize the agent registry tool.

        Args:
            available_agents: Dict mapping agent_id to agent metadata
        """
        self.available_agents = available_agents or {}

    @property
    def name(self) -> str:
        return "list_available_agents"

    @property
    def description(self) -> str:
        return "List all available agents in the system with their capabilities and descriptions"

    def get_schema(self) -> dict[str, Any]:
        """Get the OpenAI function schema for listing agents."""
        return {
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_by_capability": {
                        "type": "string",
                        "description": "Optional capability to filter agents by",
                        "default": None,
                    }
                },
                "required": [],
            }
        }

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Execute agent discovery.

        Args:
            filter_by_capability: Optional capability to filter by

        Returns:
            Dict containing available agents information
        """
        try:
            filter_capability = kwargs.get("filter_by_capability")

            agents_list = []
            for agent_id, metadata in self.available_agents.items():
                if filter_capability:
                    capabilities = metadata.get("capabilities", [])
                    if filter_capability not in capabilities:
                        continue

                agents_list.append(
                    {
                        "id": agent_id,
                        "name": metadata.get("name", agent_id),
                        "description": metadata.get("description", ""),
                        "capabilities": metadata.get("capabilities", []),
                        "status": metadata.get("status", "available"),
                    }
                )

            return {
                "success": True,
                "result": {
                    "available_agents": agents_list,
                    "total_count": len(agents_list),
                    "filtered_by": filter_capability,
                },
                "error": None,
                "tool_name": self.name,
            }

        except Exception as e:
            logger.error(f"Agent discovery failed: {str(e)}")
            raise ToolExecutionError(self.name, str(e), e) from e
