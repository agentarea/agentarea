"""ADK-Temporal Integration Package.

This package provides integration between Google's Agent Development Kit (ADK)
and Temporal workflows, enabling ADK agents to run with Temporal's durability
and workflow capabilities while preserving all ADK interfaces.
"""

# Import only the workflow class to avoid importing ADK modules at package level
# ADK modules contain restricted dependencies that cause Temporal workflow validation to fail
from .workflows.adk_agent_workflow import ADKAgentWorkflow

__all__ = [
    "ADKAgentWorkflow",
]