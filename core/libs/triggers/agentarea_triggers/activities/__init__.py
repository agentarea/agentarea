"""Trigger execution activities."""

# make_trigger_activities has been moved to agentarea_execution.activities
# Import from there for backward compatibility
from agentarea_execution.activities import make_trigger_activities

__all__ = [
    "make_trigger_activities",
]
