package gateway

import (
	"context"
	"errors"
	"time"
)

// ErrStartupDeadline is a workload that did not run before the startup timeout.
var ErrStartupDeadline = errors.New("startup deadline expired")

// StoppedError is a workload that stopped while starting.
type StoppedError interface {
	error
	Stopped() bool
}

// Begin marks the request as the one activating the workload.
func (c *ColdStart) Begin() {
	if c != nil {
		c.Activated = true
	}
}

// Fail records the step the start failed in.
func (c *ColdStart) Fail(step string) {
	if c != nil {
		c.FailedIn = step
	}
}

// Phase records how long the running or listening wait took.
func (c *ColdStart) Phase(step string, began time.Time, err error) {
	if c == nil {
		return
	}
	took := time.Since(began)
	if step == StepRunning {
		c.Running = took
	} else {
		c.Listening = took
	}
	if err != nil {
		c.FailedIn = step
	}
}

// Settle classifies the start; nil when the request activated nothing.
func (c *ColdStart) Settle(err error) *ColdStart {
	if c == nil || !c.Activated {
		return nil
	}
	c.Outcome, c.Reason = classify(c.FailedIn, err)
	return c
}

func classify(step string, err error) (ColdStartOutcome, string) {
	if err == nil {
		return ColdStartReady, ""
	}
	var stopped StoppedError
	if errors.As(err, &stopped) && stopped.Stopped() {
		return ColdStartFailed, "stopped"
	}
	switch step {
	case StepCreate:
		return ColdStartFailed, "create_failed"
	case StepRunning:
		if errors.Is(err, ErrStartupDeadline) || errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
			return ColdStartTimeout, "not_running"
		}
		return ColdStartFailed, "inspect_failed"
	case StepListening:
		return ColdStartTimeout, "not_listening"
	case StepObserver:
		return ColdStartFailed, "observer_refused"
	case StepAdmission:
		return ColdStartFailed, "admission_failed"
	default:
		return ColdStartFailed, "other"
	}
}
