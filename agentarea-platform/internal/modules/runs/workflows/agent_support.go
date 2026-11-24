package workflows

import (
	"errors"
	"fmt"
	"math/big"
	"strings"
	"time"

	"github.com/google/uuid"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// Error types the run raises and matches, as the Python workflow named them.
const (
	ErrBudgetExceeded            = "BudgetExceeded"
	ErrTokenBudgetExceeded       = "TokenBudgetExceeded"
	ErrToolCallLimitExceeded     = "ToolCallLimitExceeded"
	ErrInvalidExecutionSnapshot  = "InvalidExecutionSnapshot"
	ErrLLMAccountingUnavailable  = "LLMAccountingUnavailable"
	ErrReservedToolName          = "ReservedToolName"
	ErrRunInputExceedsWindow     = "RunInputExceedsContextWindow"
	ErrGovernanceSnapshotPersist = "GovernanceSnapshotPersistenceFailed"
	ErrGovernanceDenied          = "GovernanceDeniedError"
	ErrEscalationRequired        = "EscalationRequiredError"
	ErrSpendCapReached           = "SpendCapReached"
	ErrDependencyUnavailable     = "DependencyUnavailable"
)

// Failure reasons a stop at a limit records.
const (
	ReasonMonthlyCap = "monthly_spend_cap_exceeded"
	ReasonLLMRunCap  = "llm_run_cap_exceeded"
	ReasonIteration  = "iteration_limit"
	ReasonBudget     = "budget_exceeded"
	ReasonTokens     = "token_limit"
	ReasonToolCalls  = "tool_call_limit"
)

// Timings of the agent run (constants.py).
const (
	continuationTimeout  = 24 * time.Hour
	delegationTimeout    = 6 * time.Hour
	inputRequestTimeout  = 30 * time.Minute
	contextMaxPayload    = 1_500_000
	outputOffloadChars   = 8000
	seenURLsLimit        = 5000
	budgetWarnThreshold  = 0.8
	stoppedWhileRunning  = "Stopped by the user while this call was running. Whether it finished, and what it returned, is not known to this conversation; check before relying on its effects."
	stoppedBeforeRunning = "Not executed: the user stopped the run before this call ran."
)

func nonRetryable(msg, typ string) error {
	return temporal.NewNonRetryableApplicationError(msg, typ, nil)
}

// appErrorType is the ApplicationError type an error carries, through activity and child wrappers.
func appErrorType(err error) string {
	if appErr, ok := errors.AsType[*temporal.ApplicationError](err); ok {
		return appErr.Type()
	}
	return ""
}

// runLimitReason maps a limit error to its failure reason (run_limit_reason).
func runLimitReason(err error) string {
	switch appErrorType(err) {
	case ErrBudgetExceeded:
		return ReasonBudget
	case ErrTokenBudgetExceeded:
		return ReasonTokens
	case ErrToolCallLimitExceeded:
		return ReasonToolCalls
	}
	return ""
}

func isCancellation(err error) bool {
	if err == nil {
		return false
	}
	_, ok := errors.AsType[*temporal.CanceledError](err)
	return ok || temporal.IsCanceledError(err)
}

func spec(name string) ActivitySpec {
	for _, s := range ActivitySpecs() {
		if s.Name == name {
			return s
		}
	}
	panic("runs: no activity spec named " + name)
}

func retryPolicy(r Retry) *temporal.RetryPolicy {
	return &temporal.RetryPolicy{
		InitialInterval:    r.Initial,
		BackoffCoefficient: 2,
		MaximumInterval:    r.Max,
		MaximumAttempts:    int32(r.MaxAttempts),
	}
}

// activityCtx schedules an activity with the options of its spec; the agent
// queue is the run's own queue.
func activityCtx(ctx workflow.Context, name string, queue string, outageWindow time.Duration) workflow.Context {
	s := spec(name)
	opts := workflow.ActivityOptions{
		StartToCloseTimeout:    s.StartToClose,
		ScheduleToCloseTimeout: s.ScheduleToClose,
		ScheduleToStartTimeout: s.ScheduleToStart,
		HeartbeatTimeout:       s.Heartbeat,
		RetryPolicy:            retryPolicy(s.Retry),
		TaskQueue:              queue,
	}
	if s.OutageWindow && outageWindow > 0 {
		opts.ScheduleToCloseTimeout = outageWindow
		opts.StartToCloseTimeout = min(opts.StartToCloseTimeout, outageWindow)
	}
	if s.WaitCancellation {
		opts.WaitForCancellation = true
	}
	return workflow.WithActivityOptions(ctx, opts)
}

// ids hands out the run's deterministic event and call ids.
type ids struct {
	space uuid.UUID
	next  uint64
}

func newIDs(workflowID, runID string) *ids {
	return &ids{space: uuid.NewSHA1(uuid.NameSpaceURL, []byte("agentarea:run:"+workflowID+"/"+runID))}
}

func (g *ids) uuid() string {
	g.next++
	return uuid.NewSHA1(g.space, []byte(fmt.Sprint(g.next))).String()
}

func dec(s string) money.Decimal { return money.MustParse(s) }

func maxDec(a, b money.Decimal) money.Decimal {
	if a.Cmp(b) >= 0 {
		return a
	}
	return b
}

func minDec(a, b money.Decimal) money.Decimal {
	if a.Cmp(b) <= 0 {
		return a
	}
	return b
}

func ratOf(d money.Decimal) *big.Rat {
	r, ok := new(big.Rat).SetString(d.Plain())
	if !ok {
		panic("runs: unreadable decimal " + d.String())
	}
	return r
}

// divInt is Python's Decimal division by an int: exact at the dividend's
// exponent or the shortest exact form, else 28 significant digits.
func divInt(d money.Decimal, n int) money.Decimal {
	q := new(big.Rat).Quo(ratOf(d), new(big.Rat).SetInt64(int64(n)))
	for places := max(0, int(-d.Exponent())); places <= 40; places++ {
		scaled := new(big.Rat).Mul(q, new(big.Rat).SetInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(places)), nil)))
		if scaled.IsInt() && len(scaled.Num().String()) <= money.Precision {
			return dec(q.FloatString(places))
		}
	}
	return dec(sigDigits(q, money.Precision))
}

func sigDigits(q *big.Rat, digits int) string {
	f := new(big.Float).SetPrec(512).SetRat(q)
	return f.Text('e', digits-1)
}

// fixed is format(d, ".Nf"), ROUND_HALF_EVEN.
func fixed(d money.Decimal, places int) string {
	r := ratOf(d)
	scale := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(places)), nil)
	num := new(big.Int).Mul(r.Num(), scale)
	q, rem := new(big.Int).QuoRem(num, r.Denom(), new(big.Int))
	twice := new(big.Int).Mul(new(big.Int).Abs(rem), big.NewInt(2))
	if c := twice.Cmp(r.Denom()); c > 0 || (c == 0 && q.Bit(0) == 1) {
		if num.Sign() < 0 {
			q.Sub(q, big.NewInt(1))
		} else {
			q.Add(q, big.NewInt(1))
		}
	}
	return new(big.Rat).SetFrac(q, scale).FloatString(places)
}

func ratio(a, b money.Decimal) float64 {
	if b.Sign() <= 0 {
		return 0
	}
	f, _ := new(big.Rat).Quo(ratOf(a), ratOf(b)).Float64()
	return f
}

func floatOf(d money.Decimal) float64 {
	f, _ := ratOf(d).Float64()
	return f
}

func intLimit(p *int) (int, bool) {
	if p == nil || *p <= 0 {
		return 0, false
	}
	return *p, true
}

func policyMaxTokens(p api.Policy) (int, bool) {
	if p.Tokens == nil {
		return 0, false
	}
	return intLimit(p.Tokens.MaxTokens)
}

func policyExec(p api.Policy) api.ExecutionPolicy {
	if p.Execution == nil {
		return api.ExecutionPolicy{}
	}
	return *p.Execution
}

func ptr[T any](v T) *T { return &v }

func truncateRunes(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}
