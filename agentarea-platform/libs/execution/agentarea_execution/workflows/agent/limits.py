"""Run limits that pause a run for a continuation grant instead of failing it."""

from temporalio.exceptions import ApplicationError

# ApplicationError type -> the failure reason the continuation flow reports.
RUN_LIMIT_REASONS = {
    "BudgetExceeded": "budget_exceeded",
    "TokenBudgetExceeded": "token_limit",
    "ToolCallLimitExceeded": "tool_call_limit",
}


def run_limit_reason(error: BaseException) -> str | None:
    """The continuation failure reason for a run-limit error, None for anything else."""
    if isinstance(error, ApplicationError):
        return RUN_LIMIT_REASONS.get(error.type or "")
    return None
