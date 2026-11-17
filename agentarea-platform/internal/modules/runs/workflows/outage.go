package workflows

import (
	"errors"
	"fmt"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// Outage wait timings (outage.py).
const (
	outageInitialInterval = 2 * time.Second
	outageMaxInterval     = time.Minute
	outageTryAttempts     = 3
	outageLastTry         = time.Minute
	outageActivityTimeout = 5 * time.Minute
)

// legacyOutageWait is the wait of a run whose configuration recorded none.
func legacyOutageWait() api.OutageWait {
	return api.OutageWait{
		RetryWindow: 5 * time.Minute,
		Backoff:     []time.Duration{time.Minute, 5 * time.Minute, 10 * time.Minute},
		Deadline:    24 * time.Hour,
	}
}

func (r *agentRun) outageWait() api.OutageWait {
	w := r.cfg.OutageWait
	if w.RetryWindow <= 0 || len(w.Backoff) == 0 || w.Deadline <= 0 {
		return legacyOutageWait()
	}
	return w
}

// isOutage: an activity gave up on a retryable failure, its retries ran out, not its case.
func isOutage(err error) bool {
	a, ok := errors.AsType[*temporal.ActivityError](err)
	if !ok {
		return false
	}
	switch a.RetryState() {
	case enumspb.RETRY_STATE_TIMEOUT, enumspb.RETRY_STATE_MAXIMUM_ATTEMPTS_REACHED:
		return true
	case enumspb.RETRY_STATE_UNSPECIFIED:
		// The test server reports no retry state for a retryable failure whose retries ran out.
		app := appErr(err)
		return app != nil && !app.NonRetryable()
	case enumspb.RETRY_STATE_IN_PROGRESS, enumspb.RETRY_STATE_NON_RETRYABLE_FAILURE, enumspb.RETRY_STATE_RETRY_POLICY_NOT_SET,
		enumspb.RETRY_STATE_INTERNAL_SERVER_ERROR, enumspb.RETRY_STATE_CANCEL_REQUESTED:
		return false
	default:
		return false
	}
}

// outageService is the service the activity named as unreachable.
func outageService(err error) string {
	for _, d := range errorDetails(err) {
		if s, ok := d["service"].(string); ok {
			return s
		}
	}
	return "A service"
}

func span(d time.Duration) string {
	s := int64(d.Seconds())
	switch {
	case s%3600 == 0:
		return fmt.Sprintf("%d h", s/3600)
	case s%60 == 0:
		return fmt.Sprintf("%d min", s/60)
	}
	return fmt.Sprintf("%d s", s)
}

// executeThroughOutage runs an activity, waiting out an outage of the service
// it calls (_execute_through_outage). what says what the run is doing. A
// final failure reaches the caller as the activity's error; a run that waited
// too long gets a non-retryable DependencyUnavailable that is no ActivityError.
func (r *agentRun) executeThroughOutage(ctx workflow.Context, activity string, in, out any, what string, heartbeat time.Duration) error {
	err := r.retryThroughOutage(ctx, activity, in, out, what, heartbeat)
	if !r.waitingForOutage {
		return err
	}
	waited := workflow.Now(ctx).Sub(r.outageSince)
	service := r.outageServiceName
	if service == "" {
		service = "A service"
	}
	r.clearOutageWait()
	if err == nil {
		if lerr := r.leaveOutageWait(ctx, service, waited, ""); lerr != nil {
			return lerr
		}
		return nil
	}
	stopped := isCancellation(err) || ctx.Err() != nil
	_, wrapped := errors.AsType[*temporal.ActivityError](err)
	gaveUp := !wrapped && appErrorType(err) == ErrDependencyUnavailable
	if !stopped && !gaveUp {
		if lerr := r.leaveOutageWait(ctx, service, waited, causeText(err)); lerr != nil {
			return lerr
		}
	}
	return err
}

func (r *agentRun) retryThroughOutage(ctx workflow.Context, activity string, in, out any, what string, heartbeat time.Duration) error {
	wait := r.outageWait()
	tryTimeout := min(outageActivityTimeout, wait.RetryWindow)
	scheduleToClose := wait.RetryWindow
	policy := &temporal.RetryPolicy{InitialInterval: outageInitialInterval, BackoffCoefficient: 2, MaximumInterval: outageMaxInterval}
	var deadlineAt *time.Time
	hardCap := r.hardCap(ctx)
	var paused time.Duration
	tries := 0
	reason := ""
	giveUpAt := func() time.Time {
		if hardCap != nil && hardCap.Before(*deadlineAt) {
			return *hardCap
		}
		return *deadlineAt
	}
	for {
		r.retryOutageNow = false
		actx := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{
			StartToCloseTimeout: tryTimeout, ScheduleToCloseTimeout: scheduleToClose,
			HeartbeatTimeout: heartbeat, RetryPolicy: policy,
		})
		err := workflow.ExecuteActivity(actx, activity, in).Get(ctx, out)
		if err == nil {
			return nil
		}
		if isCancellation(err) || ctx.Err() != nil || !isOutage(err) {
			return err
		}
		reason = causeText(err)
		now := workflow.Now(ctx)
		if deadlineAt == nil {
			deadlineAt = ptr(now.Add(wait.Deadline))
			if eerr := r.enterOutageWait(ctx, outageService(err), what, reason, wait); eerr != nil {
				return eerr
			}
		}
		if !now.Before(giveUpAt()) {
			return r.gaveUp(what, reason, now, paused)
		}
		delay := min(wait.Backoff[min(tries, len(wait.Backoff)-1)], giveUpAt().Sub(now))
		tries++
		held, herr := r.holdBetweenTries(ctx, delay)
		if herr != nil {
			return herr
		}
		paused += held
		deadlineAt = ptr(deadlineAt.Add(held))
		now = workflow.Now(ctx)
		if now.After(giveUpAt()) && (held <= 0 || (hardCap != nil && !now.Before(*hardCap))) {
			return r.gaveUp(what, reason, now, paused)
		}
		window := max(giveUpAt().Sub(now), outageLastTry)
		tryTimeout = min(outageActivityTimeout, wait.RetryWindow, window)
		scheduleToClose = window
		policy = &temporal.RetryPolicy{InitialInterval: time.Second, BackoffCoefficient: 2, MaximumAttempts: outageTryAttempts}
	}
}

func (r *agentRun) gaveUp(what, reason string, now time.Time, paused time.Duration) error {
	waited := now.Sub(r.outageSince) - paused
	service := r.outageServiceName
	if service == "" {
		service = "A service"
	}
	return nonRetryable(fmt.Sprintf("%s stayed unreachable for %s while %s: %s", service, span(waited), what, reason), ErrDependencyUnavailable)
}

// holdBetweenTries sleeps delay, or less on a resume; never retries while
// paused. It returns the time paused.
func (r *agentRun) holdBetweenTries(ctx workflow.Context, delay time.Duration) (time.Duration, error) {
	if _, err := workflow.AwaitWithTimeout(ctx, delay, func() bool { return r.retryOutageNow && !r.paused }); err != nil {
		return 0, err
	}
	if !r.paused {
		return 0, nil
	}
	pausedAt := workflow.Now(ctx)
	if err := workflow.Await(ctx, func() bool { return !r.paused }); err != nil {
		return 0, err
	}
	return workflow.Now(ctx).Sub(pausedAt), nil
}

func (r *agentRun) clearOutageWait() {
	r.waitingForOutage = false
	r.outageReason = ""
	r.outageServiceName = ""
	r.outageSince = time.Time{}
	r.retryOutageNow = false
}

func (r *agentRun) enterOutageWait(ctx workflow.Context, service, what, reason string, wait api.OutageWait) error {
	r.waitingForOutage = true
	r.outageServiceName = service
	r.outageSince = workflow.Now(ctx)
	r.outageReason = fmt.Sprintf("%s is unreachable while %s; the run retries on its own: %s", service, what, reason)
	r.status = StatusWaitingForInfra
	r.emit(ctx, domain.EventTaskAwaitingInfra, map[string]any{
		"service": service, "reason": reason, "message": r.outageReason,
		"retry_in_seconds": int64(wait.Backoff[0].Seconds()), "deadline_seconds": int64(wait.Deadline.Seconds()),
		"iteration": r.iteration,
	})
	return r.persistStatus(ctx, TaskStatus{Status: StatusWaitingForInfra, ErrorMessage: r.outageReason})
}

// leaveOutageWait: the service answered, with the result or with a final error the caller handles.
func (r *agentRun) leaveOutageWait(ctx workflow.Context, service string, waited time.Duration, failure string) error {
	r.status = StatusExecuting
	data := map[string]any{"service": service, "waited_seconds": int64(waited.Seconds())}
	if failure != "" {
		data["error"] = failure
	}
	data["iteration"] = r.iteration
	r.emit(ctx, domain.EventTaskInfraRecovered, data)
	return r.persistStatus(ctx, r.statusOnly("running"))
}
