"""An agent's lifecycle, shared by every library that decides whether it may run."""

from enum import StrEnum


class AgentStatus(StrEnum):
    ACTIVE = "active"
    # Out of the working set: listed nowhere, runs nothing, still readable by id
    # so the runs it made can show who made them.
    ARCHIVED = "archived"


class AgentArchivedError(ValueError):
    """Raised when an archived agent is asked to run or change."""

    def __init__(self, agent_id) -> None:
        self.agent_id = str(agent_id)
        super().__init__(f"Agent {self.agent_id} is archived; restore it first")
