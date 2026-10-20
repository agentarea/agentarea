"""Run limits that pause a run for a continuation grant instead of failing it."""

from temporalio.exceptions import ActivityError, ApplicationError

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


# ApplicationError type of a model call refused at a monthly cap on LLM spend.
SPEND_CAP_REACHED_ERROR = "SpendCapReachedError"


def spend_cap_reached(error: BaseException) -> str | None:
    """Why a model call was refused at a monthly LLM spend cap, None for anything else."""
    cause = error.cause if isinstance(error, ActivityError) else error
    if isinstance(cause, ApplicationError) and cause.type == SPEND_CAP_REACHED_ERROR:
        return cause.message
    return None
