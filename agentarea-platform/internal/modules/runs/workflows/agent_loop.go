package workflows

import (
	"fmt"
	"strconv"

	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// mainLoop iterates until the task completes, stops at a limit, or its
// follow-up window closes.
func (r *agentRun) mainLoop(ctx workflow.Context) error {
	r.status = StatusExecuting
	if err := r.checkMonthlySpendCap(ctx); err != nil {
		return err
	}
	for {
		if r.paused {
			if err := workflow.Await(ctx, func() bool { return !r.paused }); err != nil {
				return err
			}
			if err := r.checkMonthlySpendCap(ctx); err != nil {
				return err
			}
		}
		if workflow.GetInfo(ctx).GetContinueAsNewSuggested() {
			return r.continueAsNew(ctx, "history")
		}
		r.iteration++
		if cont, reason, msg := r.shouldContinue(); !cont {
			r.iteration--
			again, err := r.stopOrContinue(ctx, reason, msg)
			if err != nil {
				return err
			}
			if again {
				continue
			}
			return nil
		}
		if err := r.executeIteration(ctx); err != nil {
			reason := runLimitReason(err)
			if reason == "" {
				return err
			}
			r.answerUnansweredToolCalls("Not executed: the run stopped at a resource limit before this call ran.")
			again, cerr := r.stopOrContinue(ctx, reason, r.runLimitMessage(reason))
			if cerr != nil {
				return cerr
			}
			if again {
				continue
			}
			return nil
		}
		if r.validationTerminal || r.status == StatusBlocked {
			return nil
		}
		if r.awaitingInput {
			if r.isDelegationChild() {
				return nil
			}
			if err := r.awaitFollowUp(ctx); err != nil {
				return err
			}
			if !r.awaitingInput {
				r.resetForFollowUp()
				if err := r.checkMonthlySpendCap(ctx); err != nil {
					return err
				}
				continue
			}
			return nil
		}
		if cont, reason, msg := r.shouldContinue(); !cont {
			again, err := r.stopOrContinue(ctx, reason, msg)
			if err != nil {
				return err
			}
			if again {
				continue
			}
			return nil
		}
		if workflow.GetInfo(ctx).GetContinueAsNewSuggested() {
			return r.continueAsNew(ctx, "history")
		}
		if r.paused {
			if err := workflow.Await(ctx, func() bool { return !r.paused }); err != nil {
				return err
			}
			if err := r.checkMonthlySpendCap(ctx); err != nil {
				return err
			}
		}
	}
}

// stopOrContinue waits for a continuation grant at a limit; false ends the loop.
func (r *agentRun) stopOrContinue(ctx workflow.Context, reason, msg string) (bool, error) {
	if reason != "" {
		granted, err := r.awaitContinuation(ctx, reason, msg)
		if err != nil {
			return false, err
		}
		if granted {
			return true, r.checkMonthlySpendCap(ctx)
		}
	}
	r.recordUnsuccessfulTermination(reason, r.terminationMessage(reason, msg))
	return false, nil
}

func (r *agentRun) shouldContinue() (bool, string, string) {
	if r.success {
		return false, "", "Goal achieved successfully"
	}
	if r.monthlyCapMessage != "" {
		return false, ReasonMonthlyCap, r.monthlyCapMessage
	}
	if msg := r.llmRunCapMessage(); msg != "" {
		return false, ReasonLLMRunCap, msg
	}
	if r.iteration > r.goal.MaxIterations {
		return false, ReasonIteration, fmt.Sprintf("Maximum iterations reached (%d)", r.goal.MaxIterations)
	}
	if r.cost.Cmp(r.budgetLimit) >= 0 {
		return false, ReasonBudget, fmt.Sprintf("Budget exceeded (%s/%s)", r.describe(r.cost), r.describe(r.budgetLimit))
	}
	return true, "", "Continue execution"
}

func (r *agentRun) runLimitMessage(reason string) string {
	switch reason {
	case ReasonTokens:
		return fmt.Sprintf("Token budget exhausted (%d/%s tokens)", r.tokensUsed, intOrNone(policyMaxTokensPtr(r.cfg.Policy)))
	case ReasonToolCalls:
		return fmt.Sprintf("Tool-call budget exhausted (%d/%s calls)", r.toolCallsUsed, intOrNone(policyExec(r.cfg.Policy).MaxToolCallsTotal))
	}
	return fmt.Sprintf("Budget exceeded (%s/%s)", r.describe(r.cost), r.describe(r.budgetLimit))
}

func policyMaxTokensPtr(p api.Policy) *int {
	if p.Tokens == nil {
		return nil
	}
	return p.Tokens.MaxTokens
}

func intOrNone(p *int) string {
	if p == nil {
		return "None"
	}
	return strconv.Itoa(*p)
}

func intOrNil(p *int) any {
	if p == nil {
		return nil
	}
	return *p
}

func (r *agentRun) terminationMessage(reason, msg string) string {
	if reason == "" || reason != r.policyFixedLimit {
		return msg
	}
	return msg + ". A workspace, agent or user policy sets this limit, so it cannot be raised"
}

func (r *agentRun) recordUnsuccessfulTermination(reason, msg string) {
	if r.success || reason == "" {
		return
	}
	r.failureReason = reason
	r.errorMessage = msg
}

func (r *agentRun) limitAtPolicyCeiling(reason string) bool {
	ceiling, ok := r.cfg.Governance.LimitCeilings[reason]
	if !ok {
		return false
	}
	c, err := money.Parse(ceiling)
	if err != nil {
		return false
	}
	var current *money.Decimal
	switch reason {
	case ReasonIteration:
		current = ptr(money.FromInt(int64(r.goal.MaxIterations)))
	case ReasonToolCalls:
		if p := policyExec(r.cfg.Policy).MaxToolCallsTotal; p != nil {
			current = ptr(money.FromInt(int64(*p)))
		}
	case ReasonTokens:
		if p := policyMaxTokensPtr(r.cfg.Policy); p != nil {
			current = ptr(money.FromInt(int64(*p)))
		}
	case ReasonBudget:
		current = &r.budgetLimit
	}
	return current != nil && current.Cmp(c) >= 0
}

// awaitContinuation idles until a grant arrives or the window expires.
func (r *agentRun) awaitContinuation(ctx workflow.Context, reason, msg string) (bool, error) {
	if reason == ReasonMonthlyCap || reason == ReasonLLMRunCap {
		return false, nil
	}
	if r.limitAtPolicyCeiling(reason) {
		r.policyFixedLimit = reason
		return false, nil
	}
	if r.interaction.Channel == "none" || r.isDelegationChild() {
		return false, nil
	}
	r.recordUnsuccessfulTermination(reason, msg)
	r.waitingContinuation = true
	r.continuationReason = reason
	r.continuationMessage = msg
	r.status = StatusWaitingForContinuation
	if err := r.persistStatus(ctx, TaskStatus{Status: StatusWaitingForContinuation, ErrorMessage: msg, FailureReason: reason}); err != nil {
		return false, err
	}
	r.emit(ctx, domain.EventTaskAwaitingContinuation, map[string]any{
		"failure_reason": reason, "message": msg, "iterations_used": r.iteration,
		"max_iterations": r.goal.MaxIterations, "cost": r.cost.String(), "budget_usd": r.budgetLimit.String(),
		"tokens_used": r.tokensUsed, "max_tokens": intOrNil(policyMaxTokensPtr(r.cfg.Policy)),
		"tool_calls_used": r.toolCallsUsed, "max_tool_calls_total": intOrNil(policyExec(r.cfg.Policy).MaxToolCallsTotal),
		"continuation_timeout_seconds": int(continuationTimeout.Seconds()),
	})
	if err := r.publish(ctx); err != nil {
		return false, err
	}
	ok, err := workflow.AwaitWithTimeout(ctx, continuationTimeout, func() bool { return !r.waitingContinuation })
	if err != nil {
		return false, err
	}
	if !ok {
		r.waitingContinuation = false
		r.status = StatusFailed
		return false, nil
	}
	r.emit(ctx, domain.EventTaskContinued, map[string]any{
		"previous_failure_reason": nullable(r.continuationReason), "continuation_count": r.continuationCount,
		"max_iterations": r.goal.MaxIterations, "budget_usd": r.budgetLimit.String(),
	})
	if err := r.publish(ctx); err != nil {
		return false, err
	}
	if err := r.persistStatus(ctx, r.statusOnly("running")); err != nil {
		return false, err
	}
	r.continuationReason = ""
	r.continuationMessage = ""
	return true, nil
}

func (r *agentRun) awaitFollowUp(ctx workflow.Context) error {
	window, ok := r.followUpWindow()
	if !ok {
		return nil
	}
	got, err := workflow.AwaitWithTimeout(ctx, window, func() bool { return len(r.messageQueue) > 0 || len(r.a2uiQueue) > 0 })
	if err != nil || !got {
		return err
	}
	r.awaitingInput = false
	return r.persistStatus(ctx, r.statusOnly("running"))
}

func (r *agentRun) resetForFollowUp() {
	r.completionPublished = false
	r.success = false
	r.status = StatusExecuting
	r.finalResponse = ""
	r.failureReason = ""
	r.errorMessage = ""
	r.blockedReason = ""
	r.validationState = "pending"
	r.validationRepairs = 0
	r.validationTerminal = false
}

// accountInference adds a paid model call to the run's spend and tokens.
func (r *agentRun) accountInference(cost money.Decimal, totalTokens int64, source string) error {
	if totalTokens <= 0 {
		return nonRetryable(source+" usage accounting is missing total_tokens", ErrLLMAccountingUnavailable)
	}
	r.cost = r.cost.Add(cost)
	r.llmCostUsed = r.llmCostUsed.Add(cost)
	r.tokensUsed += totalTokens
	r.enforceAgentSpendCap()
	return nil
}

func (r *agentRun) enforceInferenceLimits(source string) error {
	if r.cost.Cmp(r.budgetLimit) > 0 {
		return nonRetryable(fmt.Sprintf("%s exceeded the resolved run budget: %s/%s", source, r.describe(r.cost), r.describe(r.budgetLimit)), ErrBudgetExceeded)
	}
	limit, ok := policyMaxTokens(r.cfg.Policy)
	if !ok {
		return nonRetryable("effective policy is missing tokens.max_tokens", ErrInvalidExecutionSnapshot)
	}
	if r.tokensUsed > int64(limit) {
		return nonRetryable(fmt.Sprintf("%s exceeded the resolved token budget: %d/%d", source, r.tokensUsed, limit), ErrTokenBudgetExceeded)
	}
	return nil
}

func (r *agentRun) checkBudgetStatus(ctx workflow.Context) error {
	usage := ratio(r.cost, r.budgetLimit) * 100
	if usage/100 >= budgetWarnThreshold && !r.budgetWarningSent {
		r.emit(ctx, domain.EventBudgetWarning, map[string]any{
			"usage_percentage": usage, "cost": r.cost.String(), "limit": r.budgetLimit.String(),
			"message": fmt.Sprintf("Warning: Budget usage at %.1f%% ($%s/$%s)", usage, fixed(r.cost, 2), fixed(r.budgetLimit, 2)),
		})
		if err := r.publish(ctx); err != nil {
			return err
		}
		r.budgetWarningSent = true
	}
	if r.cost.Cmp(r.budgetLimit) >= 0 {
		r.emit(ctx, domain.EventBudgetExceeded, map[string]any{
			"cost": r.cost.String(), "limit": r.budgetLimit.String(),
			"message": fmt.Sprintf("Budget exceeded: $%s/$%s. Stopping execution.", fixed(r.cost, 2), fixed(r.budgetLimit, 2)),
		})
		return r.publish(ctx)
	}
	return nil
}

func (r *agentRun) llmRunCapMessage() string {
	if r.cfg.Policy.Budget == nil {
		return ""
	}
	var lowest *money.Decimal
	for _, c := range r.cfg.Policy.Budget.SpendCaps {
		if c.Category == "llm" && c.Period == "run" && (lowest == nil || c.Amount.Cmp(*lowest) < 0) {
			lowest = ptr(c.Amount)
		}
	}
	if lowest == nil || r.llmCostUsed.Cmp(*lowest) < 0 {
		return ""
	}
	return fmt.Sprintf("LLM spend cap of this run reached (%s/%s)", r.describe(r.llmCostUsed), r.describe(*lowest))
}

func (r *agentRun) agentRunSpend() money.Decimal {
	if r.agentCapCountsSvc {
		return r.ownCost().Add(r.serviceCostUsed)
	}
	return r.ownCost()
}

func (r *agentRun) enforceAgentSpendCap() {
	if r.agentSpendBaseline == nil || r.monthlyCapMessage != "" {
		return
	}
	var cap *money.Decimal
	if r.agentCapReadCurrent {
		cap = r.currentAgentCap
	} else if r.cfg.Policy.Budget != nil {
		cap = r.cfg.Policy.Budget.AgentMonthlySpendCap
	}
	if cap == nil {
		return
	}
	spent := r.agentSpendBaseline.Add(r.agentRunSpend().Sub(r.agentSpendMark))
	if spent.Cmp(*cap) >= 0 {
		r.monthlyCapMessage = r.agentCapMessage(spent, *cap)
	}
}

func (r *agentRun) agentCapMessage(spent, cap money.Decimal) string {
	unit := ""
	if r.agentCapCurrency != "" {
		unit = " " + r.agentCapCurrency
	}
	return fmt.Sprintf("Agent monthly spend cap reached (%s%s/%s%s)", spent, unit, cap, unit)
}

// checkMonthlySpendCap reads the month-to-date spend again: a scheduled,
// resumed or continued run executes after submission checked it.
func (r *agentRun) checkMonthlySpendCap(ctx workflow.Context) error {
	b := r.cfg.Policy.Budget
	if b == nil {
		return nil
	}
	var llmCaps []api.SpendCap
	for _, c := range b.SpendCaps {
		if c.Category == "llm" && c.Period == "" {
			llmCaps = append(llmCaps, c)
		}
	}
	if b.MonthlySpendCap == nil && b.AgentMonthlySpendCap == nil && len(llmCaps) == 0 {
		return nil
	}
	req := MonthlySpendCapRequest{Principal: r.principal, WorkspaceCap: b.MonthlySpendCap, AgentCap: b.AgentMonthlySpendCap, LLMCaps: llmCaps, CurrentCaps: true}
	var res MonthlySpendCapResult
	if err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityCheckMonthlySpendCap, "", 0), api.ActivityCheckMonthlySpendCap, req).Get(ctx, &res); err != nil {
		return err
	}
	r.agentCapReadCurrent = true
	r.currentAgentCap = res.AgentCap
	if res.AgentMonthToDate != nil {
		r.agentCapCurrency = res.Currency
		r.agentCapCountsSvc = res.Currency == "USD"
		r.agentSpendBaseline = res.AgentMonthToDate
		r.agentSpendMark = r.agentRunSpend()
	}
	unit := ""
	if res.Currency != "" {
		unit = " " + res.Currency
	}
	switch {
	case res.Exceeded:
		capText := "None"
		if res.Cap != nil {
			capText = res.Cap.String()
		}
		r.monthlyCapMessage = fmt.Sprintf("Workspace monthly spend cap reached (%s%s/%s%s)", res.MonthToDate, unit, capText, unit)
	case res.AgentExceeded && res.AgentCap != nil:
		mtd := money.Zero()
		if res.AgentMonthToDate != nil {
			mtd = *res.AgentMonthToDate
		}
		r.monthlyCapMessage = r.agentCapMessage(mtd, *res.AgentCap)
	case res.LLMCapMessage != "":
		r.monthlyCapMessage = res.LLMCapMessage
	}
	return nil
}
