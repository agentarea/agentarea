"""Run budget, token budget and workspace monthly spend cap enforcement."""

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from agentarea_common.money import ZERO, Money, serialize_money
    from agentarea_governance.domain.policies import effective_policy_from_json

    from ..helpers import BudgetTracker

from ...models import MonthlySpendCapRequest, MonthlySpendCapResult
from ..constants import ACTIVITY_TIMEOUT, DEFAULT_RETRY_ATTEMPTS, Activities, EventTypes
from ..retry import make_retry_policy
from .base import AgentWorkflowBase
from .patches import MONTHLY_CAP_AT_START_PATCH

MONTHLY_CAP_FAILURE_REASON = "monthly_spend_cap_exceeded"


class BudgetMixin(AgentWorkflowBase):
    """Run budget, token budget and workspace monthly spend cap enforcement."""

    @property
    def _budget(self) -> BudgetTracker:
        if self.budget_tracker is None:
            raise RuntimeError("Workflow budget tracker is not initialized")
        return self.budget_tracker

    @property
    def _own_cost(self) -> Money:
        """Model spend incurred by this task, excluding child workflows."""
        if self.budget_tracker is None:
            return ZERO
        return max(self.budget_tracker.cost - self._delegated_cost, ZERO)

    def _record_inference_usage(
        self,
        *,
        cost: Money | float,
        total_tokens: int,
        source: str,
    ) -> None:
        """Account and enforce every paid model call, including compaction."""
        if isinstance(total_tokens, bool) or not isinstance(total_tokens, int) or total_tokens <= 0:
            raise ApplicationError(
                f"{source} usage accounting is missing total_tokens",
                type="LLMAccountingUnavailable",
                non_retryable=True,
            )
        self._budget.add_cost(cost)
        if self._budget.cost > self._budget.budget_limit:
            raise ApplicationError(
                f"{source} exceeded the resolved run budget: "
                f"${self._budget.cost}/${self._budget.budget_limit}",
                type="BudgetExceeded",
                non_retryable=True,
            )

        self.state.tokens_used += total_tokens
        token_limit = ((self.state.effective_policy or {}).get("tokens") or {}).get("max_tokens")
        if isinstance(token_limit, bool) or not isinstance(token_limit, int) or token_limit <= 0:
            raise ApplicationError(
                "effective policy is missing tokens.max_tokens",
                type="InvalidExecutionSnapshot",
                non_retryable=True,
            )
        if self.state.tokens_used > token_limit:
            raise ApplicationError(
                f"{source} exceeded the resolved token budget: "
                f"{self.state.tokens_used}/{token_limit}",
                type="TokenBudgetExceeded",
                non_retryable=True,
            )

    async def _check_budget_status(self) -> None:
        """Check budget status and send warnings if needed."""
        if self._budget.should_warn():
            self._events.add_event(
                EventTypes.BUDGET_WARNING,
                {
                    "usage_percentage": self._budget.get_usage_percentage(),
                    "cost": serialize_money(self._budget.cost),
                    "limit": serialize_money(self._budget.budget_limit),
                    "message": self._budget.get_warning_message(),
                },
            )
            await self._publish_events_immediately()
            self._budget.mark_warning_sent()

        if self._budget.is_exceeded():
            self._events.add_event(
                EventTypes.BUDGET_EXCEEDED,
                {
                    "cost": serialize_money(self._budget.cost),
                    "limit": serialize_money(self._budget.budget_limit),
                    "message": self._budget.get_exceeded_message(),
                },
            )
            await self._publish_events_immediately()

    async def _check_monthly_spend_cap(self) -> None:
        """Stop the run when the workspace's month-to-date spend reached its cap.

        Submission already refused a capped workspace, but a scheduled, resumed
        or continued run executes later, so current spend is read again here.
        """
        if not workflow.patched(MONTHLY_CAP_AT_START_PATCH):
            return
        budget = effective_policy_from_json(self.state.effective_policy).budget
        cap = budget.monthly_spend_cap_usd if budget else None
        if cap is None:
            return
        result: MonthlySpendCapResult = await workflow.execute_activity(
            Activities.CHECK_MONTHLY_SPEND_CAP,
            args=[
                MonthlySpendCapRequest(
                    workspace_id=self.state.workspace_id,
                    cap_usd=cap,
                    user_context_data=self.state.user_context_data,
                )
            ],
            result_type=MonthlySpendCapResult,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
        )
        if result.exceeded:
            self._monthly_cap_message = (
                f"Workspace monthly spend cap reached "
                f"(${result.month_to_date_usd:.2f}/${result.cap_usd:.2f})"
            )
