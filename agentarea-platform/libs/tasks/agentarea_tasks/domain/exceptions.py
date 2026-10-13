"""Domain exceptions for the tasks library."""

from agentarea_common.money import Money


class AgentModelNotConfiguredError(Exception):
    """Raised when starting a run for an agent that has no model configured.

    Maps to HTTP 422 Unprocessable Entity at the API boundary. A catalog agent
    installed into a workspace with no matching model instance lands here until
    the user selects a model, instead of failing deep inside the workflow with
    an empty model name.
    """

    def __init__(self, agent_id):
        self.agent_id = str(agent_id)
        super().__init__(
            f"Agent {self.agent_id} has no model configured. "
            "Select a model for this agent before starting a run."
        )


class SchedulingNotSupportedError(Exception):
    """Raised when a task carrying ``scheduled_at`` is handed to a manager without a timer.

    Maps to HTTP 501 Not Implemented at the API boundary. Only the Temporal
    manager can defer a run; the in-process manager would otherwise execute a
    task scheduled for next Tuesday immediately.
    """

    def __init__(self, task_id):
        self.task_id = str(task_id)
        super().__init__(
            f"Task {self.task_id} is scheduled for a future time, "
            "which the in-process execution engine cannot honour."
        )


class BudgetCapExceededError(Exception):
    """Raised when a workspace's, or one agent's, month-to-date spend has reached its cap.

    ``agent_id`` is set when the cap reached is the agent's own.

    Maps to HTTP 402 Payment Required at the API boundary. The numeric
    fields are surfaced in the response body so the UI can render an
    actionable message ("you've spent X of Y, raise the cap or wait
    until next month"). The ``_usd`` amounts are in ``currency``, the billing
    currency; the names are kept for API compatibility.
    """

    def __init__(
        self,
        *,
        workspace_id: str,
        current_mtd_usd: Money,
        cap_usd: Money,
        currency: str = "USD",
        agent_id: str | None = None,
    ):
        self.workspace_id = workspace_id
        self.current_mtd_usd = current_mtd_usd
        self.cap_usd = cap_usd
        self.currency = currency
        self.agent_id = agent_id
        scope = f"Agent {agent_id}" if agent_id else f"Workspace {workspace_id}"
        # At the amounts' own precision: a cap below a cent must not read as 0.00.
        super().__init__(
            f"{scope} MTD spend {current_mtd_usd} {currency} has reached cap {cap_usd} {currency}"
        )


class RunStillClosingError(Exception):
    """Raised when a stopped or failed task's run has not closed yet.

    Maps to HTTP 409 at the API boundary. A stopped run waits for the tool call
    it interrupted to settle before it closes; until then no new run of the
    conversation can start, and a message sent to it would be dropped.
    """

    def __init__(self, task_id):
        self.task_id = str(task_id)
        super().__init__(f"Task {self.task_id} is still stopping")
