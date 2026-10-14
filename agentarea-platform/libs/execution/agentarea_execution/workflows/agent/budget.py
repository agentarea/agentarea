"""Run budget, token budget and monthly spend cap enforcement."""

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from agentarea_common.money import ZERO, Money, serialize_money, to_money
    from agentarea_governance.domain.policies import effective_policy_from_json

    from ..helpers import BudgetTracker

from ...models import MonthlySpendCapRequest, MonthlySpendCapResult
from ..constants import ACTIVITY_TIMEOUT, Activities, EventTypes
from ..retry import bookkeeping_retry_policy
from .base import AgentWorkflowBase
from .patches import MONTHLY_CAP_AT_START_PATCH

MONTHLY_CAP_FAILURE_REASON = "monthly_spend_cap_exceeded"
LLM_RUN_CAP_FAILURE_REASON = "llm_run_cap_exceeded"


class BudgetMixin(AgentWorkflowBase):
    """Run budget, token budget and monthly spend cap enforcement."""

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
        """Account and enforce one paid model call in the pre-patch order.

        Runs recorded before ``PAID_CALL_PERSISTED_BEFORE_LIMITS_PATCH`` stop on
        the run budget before counting the call's tokens; their replay needs that.
        """
        self._require_total_tokens(total_tokens, source)
        self._budget.add_cost(cost)
        self.state.llm_cost_used += to_money(cost)
        self._enforce_agent_spend_cap()
        self._enforce_run_budget(source)
        self.state.tokens_used += total_tokens
        self._enforce_token_budget(source)

    def _account_inference_usage(
        self,
        *,
        cost: Money | float,
        total_tokens: int,
        source: str,
    ) -> None:
        """Add a paid model call to the run's spend and tokens without enforcing limits.

        The caller persists the call, then calls ``_enforce_inference_limits``:
        the provider was paid either way, so the call is billed before the stop.
        """
        self._require_total_tokens(total_tokens, source)
        self._budget.add_cost(cost)
        self.state.llm_cost_used += to_money(cost)
        self.state.tokens_used += total_tokens
        self._enforce_agent_spend_cap()

    def _enforce_inference_limits(self, source: str) -> None:
        """Stop the run when accounted spend or tokens exceed the resolved limits."""
        self._enforce_run_budget(source)
        self._enforce_token_budget(source)

    @staticmethod
    def _require_total_tokens(total_tokens: int, source: str) -> None:
        if isinstance(total_tokens, bool) or not isinstance(total_tokens, int) or total_tokens <= 0:
            raise ApplicationError(
                f"{source} usage accounting is missing total_tokens",
                type="LLMAccountingUnavailable",
                non_retryable=True,
            )

    def _enforce_run_budget(self, source: str) -> None:
        if self._budget.cost > self._budget.budget_limit:
            raise ApplicationError(
                f"{source} exceeded the resolved run budget: "
                f"{self._budget.describe(self._budget.cost)}/"
                f"{self._budget.describe(self._budget.budget_limit)}",
                type="BudgetExceeded",
                non_retryable=True,
            )

    def _enforce_token_budget(self, source: str) -> None:
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

    def _llm_run_cap_message(self) -> str | None:
        """Why the run may not call its model again: its LLM spend reached a per-run cap.

        Tool spend joins the run budget but never this cap. The lowest cap applies.
        """
        budget = effective_policy_from_json(self.state.effective_policy).budget
        caps = [
            cap.amount_usd
            for cap in (budget.spend_caps or [] if budget else [])
            if cap.category == "llm" and cap.period == "run"
        ]
        if not caps or self.state.llm_cost_used < min(caps):
            return None
        return (
            f"LLM spend cap of this run reached ({self._budget.describe(self.state.llm_cost_used)}"
            f"/{self._budget.describe(min(caps))})"
        )

    @property
    def _agent_run_spend(self) -> Money:
        """What this run has spent towards its agent's cap, children excluded."""
        if self._agent_cap_counts_service:
            return self._own_cost + self.state.service_cost_used
        return self._own_cost

    def _enforce_agent_spend_cap(self) -> None:
        """Stop the run once its agent's month-to-date spend reaches the agent's cap.

        The month-to-date read at the last cap check plus what this run spent
        since then; the stop is the monthly cap's, which denies further tool
        calls at once and ends the run before its next model turn.

        The cap can be overshot: by the call that crosses it, and by what other
        runs of the same agent (including its delegated children) spend between
        two cap checks, which this run only sees at its next check.
        """
        if self._agent_spend_baseline is None or self._monthly_cap_message:
            return
        budget = effective_policy_from_json(self.state.effective_policy).budget
        cap = budget.agent_monthly_spend_cap_usd if budget else None
        if cap is None:
            return
        spent = self._agent_spend_baseline + (self._agent_run_spend - self._agent_spend_mark)
        if spent >= cap:
            self._monthly_cap_message = self._agent_cap_message(spent, cap)

    def _agent_cap_message(self, spent: Money, cap: Money) -> str:
        unit = f" {self._agent_cap_currency}" if self._agent_cap_currency else ""
        return f"Agent monthly spend cap reached ({spent}{unit}/{cap}{unit})"

    async def _check_monthly_spend_cap(self) -> None:
        """Stop the run when the workspace's or its agent's month-to-date spend reached a cap.

        Submission already refused a capped workspace or agent, but a scheduled,
        resumed or continued run executes later, so current spend is read again here.
        """
        if not workflow.patched(MONTHLY_CAP_AT_START_PATCH):
            return
        budget = effective_policy_from_json(self.state.effective_policy).budget
        cap = budget.monthly_spend_cap_usd if budget else None
        agent_cap = budget.agent_monthly_spend_cap_usd if budget else None
        llm_caps = [
            spend_cap.model_dump(mode="json", exclude_none=True)
            for spend_cap in (budget.spend_caps or [] if budget else [])
            if spend_cap.category == "llm" and spend_cap.period is None
        ]
        if cap is None and agent_cap is None and not llm_caps:
            return
        result: MonthlySpendCapResult = await workflow.execute_activity(
            Activities.CHECK_MONTHLY_SPEND_CAP,
            args=[
                MonthlySpendCapRequest(
                    workspace_id=self.state.workspace_id,
                    cap_usd=cap,
                    user_context_data=self.state.user_context_data,
                    agent_id=self.state.agent_id if agent_cap is not None or llm_caps else None,
                    agent_cap_usd=agent_cap,
                    llm_caps=llm_caps,
                )
            ],
            result_type=MonthlySpendCapResult,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=bookkeeping_retry_policy(),
        )
        if result.agent_month_to_date_usd is not None:
            self._agent_cap_currency = result.currency
            # Wallet payments are recorded in USD and only count where USD is
            # the billing currency, as they do in the ledger sum just read.
            self._agent_cap_counts_service = result.currency == "USD"
            self._agent_spend_baseline = result.agent_month_to_date_usd
            self._agent_spend_mark = self._agent_run_spend
        if result.exceeded:
            unit = f" {result.currency}" if result.currency else ""
            self._monthly_cap_message = (
                f"Workspace monthly spend cap reached "
                f"({result.month_to_date_usd}{unit}/{result.cap_usd}{unit})"
            )
        elif result.agent_exceeded and result.agent_cap_usd is not None:
            self._monthly_cap_message = self._agent_cap_message(
                result.agent_month_to_date_usd or ZERO, result.agent_cap_usd
            )
        elif result.llm_cap_message:
            self._monthly_cap_message = result.llm_cap_message
