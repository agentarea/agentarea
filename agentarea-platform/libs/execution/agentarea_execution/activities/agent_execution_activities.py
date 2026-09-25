"""Agent execution activities for Temporal workflows.

This module provides Temporal activities for agent execution:

1. **State Management**: Uses TypedDict state passed between workflow activities
2. **Flow Control**: Workflow orchestrates activities step-by-step with conditional logic
3. **Tool Integration**: Direct MCP tool calls via execute_mcp_tool_activity
4. **Message Format**: OpenAI-compatible message format for LLM interactions
5. **Execution Model**: Activity-based with explicit Temporal workflow orchestration
6. **LLM Integration**: Uses real LLM services for model resolution and execution
"""

import asyncio
import logging

from prometheus_client import Counter

from ..interfaces import ActivityDependencies
from .agent.config import make_config_activities
from .agent.context import make_context_activities
from .agent.events import make_events_activities
from .agent.files import make_files_activities
from .agent.llm import make_llm_activities
from .agent.task_state import make_task_state_activities
from .agent.tools import make_tools_activities

logger = logging.getLogger(__name__)


def _make_counter(name: str, doc: str, labels: list[str] | None = None):
    return Counter(name, doc, labels or [])


# Prometheus counter for MCP dispatch telemetry
_mcp_last_dispatch_dropped_total = _make_counter(
    "mcp_last_dispatch_dropped_total",
    "Number of last_dispatch writes dropped due to full queue",
)


# Bounded queue for fire-and-forget last_dispatch persistence (instance_id, payload)
_last_dispatch_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)


async def _flush_last_dispatch_loop(get_session) -> None:
    """Batch-flush last_dispatch updates every 500ms or 100 entries, whichever first."""
    from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
    from sqlalchemy import update

    while True:
        await asyncio.sleep(0.5)
        batch: list[tuple[str, dict]] = []
        try:
            while len(batch) < 100:
                batch.append(_last_dispatch_queue.get_nowait())
        except asyncio.QueueEmpty:
            pass
        if not batch:
            continue
        try:
            async with get_session() as session:
                for instance_id, payload in batch:
                    await session.execute(
                        update(MCPServerInstance)
                        .where(MCPServerInstance.id == instance_id)
                        .values(last_dispatch=payload)
                    )
                await session.commit()
        except Exception:
            logger.error("last_dispatch flush failed", exc_info=True)


def _enqueue_last_dispatch(instance_id: str, payload: dict) -> None:
    """Push a last_dispatch update onto the bounded queue. Never blocks."""
    try:
        _last_dispatch_queue.put_nowait((instance_id, payload))
    except asyncio.QueueFull:
        _mcp_last_dispatch_dropped_total.inc()


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
