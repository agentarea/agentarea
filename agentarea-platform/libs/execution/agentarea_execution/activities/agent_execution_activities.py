"""Agent execution activities for Temporal workflows.

This module provides Temporal activities for agent execution:

1. **State Management**: Uses TypedDict state passed between workflow activities
2. **Flow Control**: Workflow orchestrates activities step-by-step with conditional logic
3. **Tool Integration**: Direct MCP tool calls via execute_mcp_tool_activity
4. **Message Format**: OpenAI-compatible message format for LLM interactions
5. **Execution Model**: Activity-based with explicit Temporal workflow orchestration
6. **LLM Integration**: Uses real LLM services for model resolution and execution
"""

import logging

from ..interfaces import ActivityDependencies
from .agent.config import make_config_activities
from .agent.context import make_context_activities
from .agent.events import make_events_activities
from .agent.files import make_files_activities
from .agent.llm import make_llm_activities
from .agent.task_state import make_task_state_activities
from .agent.tools import make_tools_activities

logger = logging.getLogger(__name__)


def make_agent_activities(dependencies: ActivityDependencies):
    """Factory function to create agent activities with injected dependencies.

    Args:
        dependencies: Basic dependencies needed to create services

    Returns:
        List of activity functions ready for worker registration
    """
    from .dependencies import ActivityServiceContainer

    container = ActivityServiceContainer(dependencies)
    return [
        *make_config_activities(dependencies, container),
        *make_files_activities(dependencies, container),
        *make_llm_activities(dependencies, container),
        *make_tools_activities(dependencies, container),
        *make_events_activities(dependencies, container),
        *make_task_state_activities(dependencies, container),
        *make_context_activities(dependencies, container),
    ]
