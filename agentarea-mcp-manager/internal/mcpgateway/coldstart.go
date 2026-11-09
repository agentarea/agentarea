package mcpgateway

import (
	"context"
	"errors"
	"time"
)

// activationStep is the step of a cold start that failed. Create, running and
// listening are also the timed phases.
type activationStep string

const (
	stepCreate    activationStep = "create"
	stepRunning   activationStep = "running"
	stepListening activationStep = "listening"
	stepObserver  activationStep = "observer"
	stepAdmission activationStep = "admission"
)

// errStartupDeadline is the startup timeout expiring while the runtime waits
// for a workload to report running.
var errStartupDeadline = errors.New("startup deadline expired")

type coldStartKey struct{}

// withColdStart hands EnsureReady the report of the activation it may begin.
func withColdStart(ctx context.Context, report *ColdStart) context.Context {
	return context.WithValue(ctx, coldStartKey{}, report)
}

// coldStartFrom is the report the gateway asked for, or nil.
func coldStartFrom(ctx context.Context) *ColdStart {
	report, _ := ctx.Value(coldStartKey{}).(*ColdStart)
	return report
}

func (c *ColdStart) begin() {
	if c != nil {
		c.activated = true
	}
}

func (c *ColdStart) fail(step activationStep) {
	if c != nil {
		c.failedIn = step
	}
}

// phase times a running or listening wait that began at began.
func (c *ColdStart) phase(step activationStep, began time.Time, err error) {
	if c == nil {
		return
	}
	took := time.Since(began)
	if step == stepRunning {
		c.Running = took
	} else {
		c.Listening = took
	}
	if err != nil {
		c.failedIn = step
	}
}

// settle closes the report with the activation's result, or returns nil when
// the request found its workload already up.
func (c *ColdStart) settle(err error) *ColdStart {
	if !c.activated {
		return nil
	}
	c.Outcome, c.Reason = classifyColdStart(c.failedIn, err)
	return c
}

// classifyColdStart names how an activation ended from the step that failed
// and its error. Waiting out the startup timeout is a timeout; everything
// else that stops a start is a failure.
func classifyColdStart(step activationStep, err error) (ColdStartOutcome, string) {
	if err == nil {
		return ColdStartReady, ""
	}
	var stopped *workloadStoppedDuringStartupError
	if errors.As(err, &stopped) {
		return ColdStartFailed, "stopped"
	}
	switch step {
	case stepCreate:
		return ColdStartFailed, "create_failed"
	case stepRunning:
		if errors.Is(err, errStartupDeadline) || errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
			return ColdStartTimeout, "not_running"
		}
		return ColdStartFailed, "inspect_failed"
	case stepListening:
		return ColdStartTimeout, "not_listening"
	case stepObserver:
		return ColdStartFailed, "observer_refused"
	case stepAdmission:
		return ColdStartFailed, "admission_failed"
	default:
		return ColdStartFailed, "other"
	}
}
