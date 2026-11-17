package runtime

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/gateway"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

const (
	backoffBase        = time.Second
	backoffCap         = 30 * time.Second
	maxServerOutput    = 1000
	runningPoll        = 500 * time.Millisecond
	listeningPoll      = 250 * time.Millisecond
	stoppedWatchPoll   = time.Second
	cleanupTimeout     = 30 * time.Second
	failureMarkTimeout = 10 * time.Second
)

var ansiEscapeRE = regexp.MustCompile(`\x1b\[[0-9;?]*[ -/]*[@-~]`)

// StartupFailureError is a classified start failure, with the backoff in force.
type StartupFailureError struct {
	reason string
	cause  error
	delay  time.Duration
}

func (e *StartupFailureError) Error() string {
	return "MCP workload failed during startup: " + e.reason
}

// Unwrap is the cause.
func (e *StartupFailureError) Unwrap() error { return e.cause }

// FailureReason is the caller-safe reason.
func (e *StartupFailureError) FailureReason() string { return e.reason }

// RetryDelay is when a retry may start the workload again.
func (e *StartupFailureError) RetryDelay() time.Duration { return e.delay }

// StartBackoffError is a start refused while the previous failure's backoff runs.
type StartBackoffError struct {
	reason string
	delay  time.Duration
}

func (e *StartBackoffError) Error() string {
	return "MCP instance is failing after a startup failure: " + e.reason
}

// FailureReason is the previous failure's reason.
func (e *StartBackoffError) FailureReason() string { return e.reason }

// RetryDelay is the backoff left.
func (e *StartBackoffError) RetryDelay() time.Duration { return e.delay }

type stoppedError struct {
	status string
	output string
}

func (e *stoppedError) Error() string {
	return fmt.Sprintf("MCP workload stopped while starting (state %q)", e.status)
}

func (e *stoppedError) Stopped() bool { return true }

func (e *stoppedError) FailureReason() string {
	reason := "workload stopped during startup"
	if state := safeState(e.status); state != "" {
		reason = fmt.Sprintf("workload stopped during startup (state %s)", state)
	}
	if out := outputTail(e.output); out != "" {
		reason += ": " + out
	}
	return reason
}

type failureReason interface{ FailureReason() string }

type retryDelay interface{ RetryDelay() time.Duration }

func outputTail(output string) string {
	text := strings.Join(strings.FieldsFunc(strings.ToValidUTF8(ansiEscapeRE.ReplaceAllString(output, ""), ""), func(r rune) bool {
		return unicode.IsSpace(r) || unicode.IsControl(r)
	}), " ")
	if len(text) <= maxServerOutput {
		return text
	}
	tail := text[len(text)-maxServerOutput:]
	for len(tail) > 0 && !utf8.RuneStart(tail[0]) {
		tail = tail[1:]
	}
	return "..." + tail
}

func backoff(consecutive int) time.Duration {
	if consecutive <= 0 {
		return 0
	}
	d := backoffBase
	for attempt := 1; attempt < consecutive && d < backoffCap; attempt++ {
		d *= 2
		if d > backoffCap {
			return backoffCap
		}
	}
	return d
}

type failureState struct {
	consecutive int
	reason      string
	retryAt     time.Time
}

func (r *Runtime) startBackoff(instanceID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	st, ok := r.failures[instanceID]
	if !ok {
		return nil
	}
	if d := time.Until(st.retryAt); d > 0 {
		return &StartBackoffError{reason: st.reason, delay: d}
	}
	return nil
}

func (r *Runtime) recordFailure(instanceID string, cause error, fallback string) *StartupFailureError {
	reason := fallback
	var classified failureReason
	if errors.As(cause, &classified) && strings.TrimSpace(classified.FailureReason()) != "" {
		reason = classified.FailureReason()
	}
	r.mu.Lock()
	st := r.failures[instanceID]
	st.consecutive++
	d := backoff(st.consecutive)
	st.reason, st.retryAt = reason, time.Now().Add(d)
	r.failures[instanceID] = st
	r.mu.Unlock()
	return &StartupFailureError{reason: reason, cause: cause, delay: d}
}

func (r *Runtime) clearFailure(instanceID string) {
	r.mu.Lock()
	delete(r.failures, instanceID)
	r.mu.Unlock()
}

func ready(status string) bool {
	switch strings.ToLower(status) {
	case "running", "healthy", "ready":
		return true
	}
	return false
}

func stopped(status string) bool {
	switch strings.ToLower(status) {
	case "stopped", "exited", "dead", "error", "failed":
		return true
	}
	return false
}

func safeState(status string) string {
	switch s := strings.ToLower(strings.TrimSpace(status)); s {
	case "created", "creating", "pending", "running", "healthy", "ready",
		"stopped", "exited", "dead", "error", "failed", "restarting", "paused":
		return s
	}
	return ""
}

// ensureReady brings the workload up and returns its upstream URL: a stopped
// workload is replaced, a missing one created, then the runtime waits for it
// to run and (on this network) to listen.
func (r *Runtime) ensureReady(ctx context.Context, inst *instance, report *gateway.ColdStart) (string, error) {
	if err := r.startBackoff(inst.ID); err != nil {
		return "", err
	}
	t, _ := inst.Spec["type"].(string)
	if t != "docker" && t != "command" && t != "kubernetes" {
		return "", fmt.Errorf("MCP demand gateway supports container-backed instances only, got %q", t)
	}
	status, statusErr := r.d.Backend.Status(ctx, inst.ID)
	if statusErr != nil && !errors.Is(statusErr, workload.ErrNotFound) {
		return "", fmt.Errorf("inspect MCP runtime status: %w", statusErr)
	}
	if statusErr == nil && stopped(status.Status) {
		if err := r.delete(ctx, inst, BoundaryDeletion); err != nil {
			return "", fmt.Errorf("remove stopped MCP workload: %w", err)
		}
		statusErr = workload.ErrNotFound
	}
	opID := ""
	activating := false
	if errors.Is(statusErr, workload.ErrNotFound) {
		activating = true
		report.Begin()
		opID = uuid.NewString()
		if err := r.observeOperation(ctx, inst, opID, OperationCreation, OperationStarted); err != nil {
			report.Fail(gateway.StepObserver)
			return "", err
		}
		if err := r.create(ctx, inst); err != nil {
			report.Fail(gateway.StepCreate)
			failure := r.recordFailure(inst.ID, err, "workload failed during startup")
			return "", errors.Join(failure,
				r.observeOperation(context.WithoutCancel(ctx), inst, opID, OperationCreation, OperationFailed),
				r.observeBoundary(context.WithoutCancel(ctx), inst, opID, BoundaryCreationFailed))
		}
		if err := r.observeOperation(ctx, inst, opID, OperationCreation, OperationCompleted); err != nil {
			report.Fail(gateway.StepObserver)
			return "", r.cleanupFailedStart(inst, err)
		}
	}
	deadline := time.Now().Add(r.d.Config.StartupTimeout)
	if statusErr != nil || !ready(status.Status) {
		if !activating {
			activating = true
			report.Begin()
			opID = uuid.NewString()
		}
		began := time.Now()
		var err error
		status, err = r.awaitRunning(ctx, inst)
		report.Phase(gateway.StepRunning, began, err)
		if err != nil {
			return "", r.recordFailure(inst.ID, err, "workload did not become ready during startup")
		}
	}
	if activating && r.d.Remote == nil && status.InternalURL != "" {
		began := time.Now()
		err := r.awaitListening(ctx, inst, status.InternalURL, deadline)
		report.Phase(gateway.StepListening, began, err)
		if err != nil {
			reason := fmt.Sprintf("workload did not listen within %s", r.d.Config.StartupTimeout)
			if status.Port > 0 {
				reason = fmt.Sprintf("workload did not listen on port %d within %s", status.Port, r.d.Config.StartupTimeout)
			}
			return "", r.cleanupFailedStart(inst, r.recordFailure(inst.ID, err, reason))
		}
	}
	if activating {
		if err := r.observeBoundary(context.WithoutCancel(ctx), inst, opID, BoundaryActivation); err != nil {
			report.Fail(gateway.StepObserver)
			return "", r.cleanupFailedStart(inst, err)
		}
	}
	r.clearFailure(inst.ID)
	return r.upstreamURL(inst, status)
}

func (r *Runtime) create(ctx context.Context, inst *instance) error {
	spec, err := r.buildSpec(ctx, inst)
	if err != nil {
		return err
	}
	if _, err := r.d.Backend.Create(ctx, spec); err != nil {
		r.d.Log.Error("MCP workload could not be created", "instance_id", inst.ID, "error", err)
		return fmt.Errorf("create MCP workload: %w", err)
	}
	r.d.Log.Info("MCP workload created", "instance_id", inst.ID)
	return nil
}

func (r *Runtime) upstreamURL(inst *instance, status workload.Status) (string, error) {
	if r.d.Remote != nil {
		return r.d.Remote.InstanceProxyURL(inst.ID), nil
	}
	if status.InternalURL == "" {
		return "", fmt.Errorf("MCP workload of instance %s reports no internal URL", inst.ID)
	}
	return strings.TrimRight(status.InternalURL, "/") + "/mcp", nil
}

func (r *Runtime) awaitRunning(ctx context.Context, inst *instance) (workload.Status, error) {
	deadline := time.NewTimer(r.d.Config.StartupTimeout)
	defer deadline.Stop()
	tick := time.NewTicker(runningPoll)
	defer tick.Stop()
	last := ""
	for {
		st, err := r.d.Backend.Status(ctx, inst.ID)
		if err == nil {
			last = st.Status
			if ready(st.Status) {
				return st, nil
			}
			if stopped(st.Status) {
				return workload.Status{}, r.cleanupFailedStart(inst, &stoppedError{status: st.Status, output: st.Message})
			}
		} else if !errors.Is(err, workload.ErrNotFound) {
			return workload.Status{}, r.cleanupFailedStart(inst, &StartupFailureError{
				reason: "workload could not be inspected during startup",
				cause:  fmt.Errorf("inspect MCP runtime while starting: %w", err),
			})
		}
		select {
		case <-ctx.Done():
			return workload.Status{}, r.cleanupFailedStart(inst, &StartupFailureError{reason: r.readinessReason(last), cause: ctx.Err()})
		case <-deadline.C:
			return workload.Status{}, r.cleanupFailedStart(inst, &StartupFailureError{reason: r.readinessReason(last), cause: gateway.ErrStartupDeadline})
		case <-tick.C:
		}
	}
}

func (r *Runtime) readinessReason(last string) string {
	reason := fmt.Sprintf("workload did not become ready within %s", r.d.Config.StartupTimeout)
	if s := safeState(last); s != "" {
		return fmt.Sprintf("%s (last state: %s)", reason, s)
	}
	return reason
}

// awaitListening dials the workload until it accepts, watching for it to stop.
func (r *Runtime) awaitListening(ctx context.Context, inst *instance, internalURL string, deadline time.Time) error {
	waitCtx, cancel := context.WithCancelCause(ctx)
	defer cancel(nil)
	go func() {
		t := time.NewTicker(stoppedWatchPoll)
		defer t.Stop()
		for {
			select {
			case <-waitCtx.Done():
				return
			case <-t.C:
			}
			st, err := r.d.Backend.Status(waitCtx, inst.ID)
			if err == nil && stopped(st.Status) {
				cancel(&stoppedError{status: st.Status, output: st.Message})
				return
			}
		}
	}()
	err := waitListening(waitCtx, internalURL, deadline)
	if err != nil && ctx.Err() == nil {
		if cause := context.Cause(waitCtx); cause != nil && !errors.Is(cause, context.Canceled) {
			return cause
		}
	}
	return err
}

func waitListening(ctx context.Context, rawURL string, deadline time.Time) error {
	u, err := url.Parse(rawURL)
	if err != nil || u.Host == "" {
		return fmt.Errorf("workload URL %q has no host", rawURL)
	}
	host := u.Host
	if u.Port() == "" {
		port := "80"
		if u.Scheme == "https" {
			port = "443"
		}
		host = net.JoinHostPort(u.Hostname(), port)
	}
	ctx, cancel := context.WithDeadline(ctx, deadline)
	defer cancel()
	var d net.Dialer
	for {
		conn, err := d.DialContext(ctx, "tcp", host)
		if err == nil {
			return conn.Close()
		}
		t := time.NewTimer(listeningPoll)
		select {
		case <-ctx.Done():
			t.Stop()
			return fmt.Errorf("workload at %s did not accept connections: %w", host, err)
		case <-t.C:
		}
	}
}

func (r *Runtime) cleanupFailedStart(inst *instance, cause error) error {
	ctx, cancel := context.WithTimeout(context.Background(), cleanupTimeout)
	defer cancel()
	err := r.delete(ctx, inst, BoundaryFailedStartCleanup)
	if err == nil {
		return cause
	}
	cleanup := fmt.Errorf("cleanup failed MCP activation: %w", err)
	var classified failureReason
	if errors.As(cause, &classified) {
		var d time.Duration
		var rd retryDelay
		if errors.As(cause, &rd) {
			d = rd.RetryDelay()
		}
		return &StartupFailureError{reason: classified.FailureReason(), cause: errors.Join(cause, cleanup), delay: d}
	}
	return errors.Join(cause, cleanup)
}

// remove deletes the workload for good (retirement, reaping, a failed admission).
func (r *Runtime) remove(ctx context.Context, inst *instance) error {
	if err := r.delete(ctx, inst, BoundaryDeletion); err != nil {
		return err
	}
	r.clearFailure(inst.ID)
	return nil
}

func (r *Runtime) delete(ctx context.Context, inst *instance, b Boundary) error {
	opID := uuid.NewString()
	if err := r.observeBoundary(ctx, inst, opID, b); err != nil {
		return err
	}
	if err := r.d.Backend.Delete(ctx, inst.ID); err != nil && !errors.Is(err, workload.ErrNotFound) {
		return errors.Join(fmt.Errorf("delete MCP workload: %w", err),
			r.observeOperation(context.WithoutCancel(ctx), inst, opID, OperationDeletion, OperationFailed))
	}
	return r.observeOperation(context.WithoutCancel(ctx), inst, opID, OperationDeletion, OperationCompleted)
}

func (r *Runtime) observeOperation(ctx context.Context, inst *instance, opID string, k OperationKind, p OperationPhase) error {
	return r.observer.Operation(ctx, Operation{InstanceID: inst.ID, WorkspaceID: inst.WorkspaceID,
		OperationID: opID, Kind: k, Phase: p, ObservedAt: time.Now().UTC()})
}

func (r *Runtime) observeBoundary(ctx context.Context, inst *instance, opID string, b Boundary) error {
	return r.observer.Boundary(ctx, BoundaryObservation{InstanceID: inst.ID, WorkspaceID: inst.WorkspaceID, OperationID: opID, Boundary: b})
}
