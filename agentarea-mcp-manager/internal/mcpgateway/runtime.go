package mcpgateway

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/listener"
	"github.com/agentarea/mcp-manager/internal/mcpbase"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/providers"
	"github.com/google/uuid"
)

// ProviderSelector resolves the data plane that owns one instance. The demand
// runtime depends on this capability rather than on the concrete provider
// registry, so lifecycle behaviour can be exercised without a live data plane.
type ProviderSelector interface {
	GetProvider(*models.MCPServerInstance) (providers.Provider, error)
}

// RemoteUpstream addresses MCP workloads that run on a separate data plane.
//
// The token is this control plane's machine credential for that host. It is
// attached to the outgoing hop by the gateway and never travels to the caller,
// so an agent speaking MCP to the manager cannot read or replay it.
type RemoteUpstream struct {
	BaseURL string
	Token   string
}

// InstanceProxyURL is the data plane's authenticated entry point for one
// instance. The data plane owns the container and starts it on demand behind
// this path, so the control plane never needs a routable address of its own.
func (u RemoteUpstream) InstanceProxyURL(instanceID string) string {
	return strings.TrimRight(u.BaseURL, "/") + "/dataplane/v1/instances/" + instanceID + "/proxy/mcp"
}

const (
	startFailureBackoffBase = time.Second
	startFailureBackoffCap  = 30 * time.Second
)

type startFailureState struct {
	consecutive int
	reason      string
	retryAt     time.Time
}

type failureReasonError interface {
	FailureReason() string
}

type retryDelayError interface {
	RetryDelay() time.Duration
}

// StartupFailureError exposes a classified start failure without returning
// workload output. Cause remains available to the manager for diagnostics.
type StartupFailureError struct {
	reason     string
	cause      error
	retryDelay time.Duration
}

func (e *StartupFailureError) Error() string {
	return "MCP workload failed during startup: " + e.reason
}

func (e *StartupFailureError) Unwrap() error {
	return e.cause
}

func (e *StartupFailureError) FailureReason() string {
	return e.reason
}

func (e *StartupFailureError) RetryDelay() time.Duration {
	return e.retryDelay
}

// StartBackoffError says an instance is still inside its failed-start cooldown.
type StartBackoffError struct {
	reason     string
	retryDelay time.Duration
}

func (e *StartBackoffError) Error() string {
	return "MCP instance is failing after a startup failure: " + e.reason
}

func (e *StartBackoffError) FailureReason() string {
	return e.reason
}

func (e *StartBackoffError) RetryDelay() time.Duration {
	return e.retryDelay
}

type workloadStoppedDuringStartupError struct {
	status string
}

func (e *workloadStoppedDuringStartupError) Error() string {
	return fmt.Sprintf("MCP workload stopped while starting (state %q)", e.status)
}

func (e *workloadStoppedDuringStartupError) FailureReason() string {
	if state := safeStartupState(e.status); state != "" {
		return fmt.Sprintf("workload stopped during startup (state %s)", state)
	}
	return "workload stopped during startup"
}

func startFailureBackoff(consecutive int) time.Duration {
	if consecutive <= 0 {
		return 0
	}
	delay := startFailureBackoffBase
	for attempt := 1; attempt < consecutive && delay < startFailureBackoffCap; attempt++ {
		delay *= 2
		if delay > startFailureBackoffCap {
			return startFailureBackoffCap
		}
	}
	return delay
}

func (r *ProviderRuntime) startBackoff(instanceID string) error {
	r.startFailuresMu.Lock()
	defer r.startFailuresMu.Unlock()
	state, exists := r.startFailures[instanceID]
	if !exists {
		return nil
	}
	retryDelay := time.Until(state.retryAt)
	if retryDelay <= 0 {
		return nil
	}
	return &StartBackoffError{reason: state.reason, retryDelay: retryDelay}
}

func (r *ProviderRuntime) recordStartFailure(instanceID string, cause error, fallback string) *StartupFailureError {
	reason := fallback
	var classified failureReasonError
	if errors.As(cause, &classified) && strings.TrimSpace(classified.FailureReason()) != "" {
		reason = classified.FailureReason()
	}

	r.startFailuresMu.Lock()
	if r.startFailures == nil {
		r.startFailures = make(map[string]startFailureState)
	}
	state := r.startFailures[instanceID]
	state.consecutive++
	delay := startFailureBackoff(state.consecutive)
	state.reason = reason
	state.retryAt = time.Now().Add(delay)
	r.startFailures[instanceID] = state
	r.startFailuresMu.Unlock()

	return &StartupFailureError{reason: reason, cause: cause, retryDelay: delay}
}

func (r *ProviderRuntime) clearStartFailure(instanceID string) {
	r.startFailuresMu.Lock()
	delete(r.startFailures, instanceID)
	r.startFailuresMu.Unlock()
}

type ProviderRuntime struct {
	providers      ProviderSelector
	backend        backends.Backend
	config         *config.Config
	startupTimeout time.Duration
	remote         *RemoteUpstream
	observer       RuntimeObserver

	startFailuresMu sync.Mutex
	startFailures   map[string]startFailureState
}

func NewProviderRuntime(providerManager ProviderSelector, backend backends.Backend, cfg *config.Config, startupTimeout time.Duration, remote *RemoteUpstream) (*ProviderRuntime, error) {
	if providerManager == nil || backend == nil || cfg == nil || startupTimeout <= 0 {
		return nil, fmt.Errorf("MCP provider runtime requires providers, backend, config, and positive startup timeout")
	}
	if remote != nil && (remote.BaseURL == "" || remote.Token == "") {
		return nil, fmt.Errorf("a remote MCP upstream requires both a base URL and a token")
	}
	return &ProviderRuntime{
		providers:      providerManager,
		backend:        backend,
		config:         cfg,
		startupTimeout: startupTimeout,
		remote:         remote,
		startFailures:  make(map[string]startFailureState),
	}, nil
}

func (r *ProviderRuntime) EnsureReady(ctx context.Context, instance *models.MCPServerInstance) (string, error) {
	if err := r.startBackoff(instance.InstanceID); err != nil {
		return "", err
	}
	provider, err := r.providers.GetProvider(instance)
	if err != nil {
		return "", err
	}
	instanceType, _ := instance.JSONSpec["type"].(string)
	if instanceType != "docker" && instanceType != "command" && instanceType != "kubernetes" {
		return "", fmt.Errorf("MCP demand gateway supports container-backed instances only, got %q", instanceType)
	}
	status, statusErr := r.backend.GetInstanceStatus(ctx, instance.InstanceID)
	if statusErr != nil && !errors.Is(statusErr, backends.ErrInstanceNotFound) {
		return "", fmt.Errorf("inspect MCP runtime status: %w", statusErr)
	}
	if statusErr == nil && runtimeStatusStopped(status.Status) {
		// A stopped workload never becomes ready again, so replace it rather
		// than waiting for the startup deadline.
		if err := r.delete(ctx, instance, BoundaryDeletion); err != nil {
			return "", fmt.Errorf("remove stopped MCP workload: %w", err)
		}
		statusErr = backends.ErrInstanceNotFound
	}
	operationID := ""
	activating := false
	if errors.Is(statusErr, backends.ErrInstanceNotFound) {
		activating = true
		operationID = r.newOperationID()
		if err := r.observeOperation(ctx, instance, operationID, OperationCreation, OperationStarted); err != nil {
			return "", err
		}
		if err := provider.CreateInstance(ctx, instance); err != nil {
			failure := r.recordStartFailure(instance.InstanceID, err, "workload failed during startup")
			observeErr := r.observeOperation(context.WithoutCancel(ctx), instance, operationID, OperationCreation, OperationFailed)
			boundaryErr := r.observeBoundary(context.WithoutCancel(ctx), instance, operationID, BoundaryCreationFailed)
			return "", errors.Join(failure, observeErr, boundaryErr)
		}
		if err := r.observeOperation(ctx, instance, operationID, OperationCreation, OperationCompleted); err != nil {
			return "", r.cleanupFailedStart(instance, err)
		}
	}
	startDeadline := time.Now().Add(r.startupTimeout)
	if statusErr != nil || !runtimeStatusReady(status.Status) {
		if !activating {
			activating = true
			operationID = r.newOperationID()
		}
		if status, err = r.awaitRunning(ctx, instance); err != nil {
			return "", r.recordStartFailure(instance.InstanceID, err, "workload did not become ready during startup")
		}
	}
	// A running container may not have bound the bridge port while its package
	// installs or its stdio server initializes.
	if activating && r.remote == nil && status != nil && status.InternalURL != "" {
		if err := r.awaitListening(ctx, instance, status.InternalURL, startDeadline); err != nil {
			port := status.Port
			if port <= 0 {
				port, _ = instancePort(instance, instanceType)
			}
			reason := fmt.Sprintf("workload did not listen within %s", r.startupTimeout)
			if port > 0 {
				reason = fmt.Sprintf("workload did not listen on port %d within %s", port, r.startupTimeout)
			}
			failure := r.recordStartFailure(instance.InstanceID, err, reason)
			return "", r.cleanupFailedStart(instance, failure)
		}
	}
	if activating {
		if err := r.observeBoundary(context.WithoutCancel(ctx), instance, operationID, BoundaryActivation); err != nil {
			return "", r.cleanupFailedStart(instance, err)
		}
	}
	r.clearStartFailure(instance.InstanceID)
	return r.upstreamURL(instance, instanceType)
}

// awaitRunning polls the backend until the workload reports running, within
// the startup timeout. A wait that fails tears the workload down.
func (r *ProviderRuntime) awaitRunning(ctx context.Context, instance *models.MCPServerInstance) (*backends.InstanceStatus, error) {
	deadline := time.NewTimer(r.startupTimeout)
	defer deadline.Stop()
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	lastState := ""
	for {
		status, statusErr := r.backend.GetInstanceStatus(ctx, instance.InstanceID)
		if statusErr == nil {
			lastState = status.Status
		}
		if statusErr == nil && runtimeStatusReady(status.Status) {
			return status, nil
		}
		if statusErr != nil && !errors.Is(statusErr, backends.ErrInstanceNotFound) {
			cause := &StartupFailureError{
				reason: "workload could not be inspected during startup",
				cause:  fmt.Errorf("inspect MCP runtime while starting: %w", statusErr),
			}
			return nil, r.cleanupFailedStart(instance, cause)
		}
		if statusErr == nil && runtimeStatusStopped(status.Status) {
			return nil, r.cleanupFailedStart(instance, &workloadStoppedDuringStartupError{status: status.Status})
		}
		select {
		case <-ctx.Done():
			cause := &StartupFailureError{
				reason: startupReadinessFailureReason(r.startupTimeout, lastState),
				cause:  ctx.Err(),
			}
			return nil, r.cleanupFailedStart(instance, cause)
		case <-deadline.C:
			cause := &StartupFailureError{
				reason: startupReadinessFailureReason(r.startupTimeout, lastState),
				cause:  errors.New("startup deadline expired"),
			}
			return nil, r.cleanupFailedStart(instance, cause)
		case <-ticker.C:
		}
	}
}

// awaitListening waits for the workload to accept connections and gives up as
// soon as it stops: mcp-base exits when its package fails to install or its
// stdio server fails to initialize, and that workload will never listen.
func (r *ProviderRuntime) awaitListening(ctx context.Context, instance *models.MCPServerInstance, internalURL string, deadline time.Time) error {
	waitCtx, cancel := context.WithCancelCause(ctx)
	defer cancel(nil)
	go func() {
		ticker := time.NewTicker(time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-waitCtx.Done():
				return
			case <-ticker.C:
			}
			status, err := r.backend.GetInstanceStatus(waitCtx, instance.InstanceID)
			if err == nil && runtimeStatusStopped(status.Status) {
				cancel(&workloadStoppedDuringStartupError{status: status.Status})
				return
			}
		}
	}()
	err := listener.Wait(waitCtx, internalURL, deadline)
	if err != nil && ctx.Err() == nil {
		if cause := context.Cause(waitCtx); cause != nil && !errors.Is(cause, context.Canceled) {
			return cause
		}
	}
	return err
}

// upstreamURL is where the gateway proxies this instance's MCP traffic.
func (r *ProviderRuntime) upstreamURL(instance *models.MCPServerInstance, instanceType string) (string, error) {
	// A remote data plane exposes one authenticated path per instance and keeps
	// the container unaddressable from here, so the local service URL -- which
	// resolves nothing in this mode -- must not be consulted, and the port in
	// the spec is the data plane's business rather than ours.
	if r.remote != nil {
		return r.remote.InstanceProxyURL(instance.InstanceID), nil
	}
	port, err := instancePort(instance, instanceType)
	if err != nil {
		return "", err
	}
	var base string
	if r.config.Environment == "kubernetes" {
		base = r.config.Kubernetes.GetInternalServiceURL(instance.InstanceID, port)
	} else {
		base = r.config.GetServiceURL(instance.InstanceID, port)
	}
	return strings.TrimRight(base, "/") + "/mcp", nil
}

// instancePort resolves the port the workload listens on.
//
// A declared-but-unusable port is a spec error, not an invitation to guess:
// silently falling back to 8000 would proxy the request to whatever happens to
// be listening there. Only an absent port takes the documented default.
func instancePort(instance *models.MCPServerInstance, instanceType string) (int, error) {
	if instanceType == "command" {
		// command instances run behind mcp-base's bridge, which always listens
		// here regardless of any port in the spec.
		return mcpbase.Port, nil
	}
	rawPort, declared := instance.JSONSpec["port"]
	if !declared || rawPort == nil {
		return 8000, nil
	}
	var parsed int
	switch value := rawPort.(type) {
	case float64:
		parsed = int(value)
		if float64(parsed) != value {
			return 0, fmt.Errorf("MCP instance port %v is not an integer", value)
		}
	case int:
		parsed = value
	default:
		return 0, fmt.Errorf("MCP instance port %v is not a number", rawPort)
	}
	if parsed <= 0 || parsed > 65535 {
		return 0, fmt.Errorf("MCP instance port %d is outside 1-65535", parsed)
	}
	return parsed, nil
}

func (r *ProviderRuntime) cleanupFailedStart(instance *models.MCPServerInstance, cause error) error {
	cleanupCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := r.delete(cleanupCtx, instance, BoundaryFailedStartCleanup); err != nil {
		var classified failureReasonError
		var retryable retryDelayError
		if errors.As(cause, &classified) {
			var delay time.Duration
			if errors.As(cause, &retryable) {
				delay = retryable.RetryDelay()
			}
			return &StartupFailureError{
				reason:     classified.FailureReason(),
				cause:      errors.Join(cause, fmt.Errorf("cleanup failed MCP activation: %w", err)),
				retryDelay: delay,
			}
		}
		return errors.Join(cause, fmt.Errorf("cleanup failed MCP activation: %w", err))
	}
	return cause
}

func (r *ProviderRuntime) Delete(ctx context.Context, instance *models.MCPServerInstance) error {
	if err := r.delete(ctx, instance, BoundaryDeletion); err != nil {
		return err
	}
	r.clearStartFailure(instance.InstanceID)
	return nil
}

func (r *ProviderRuntime) delete(ctx context.Context, instance *models.MCPServerInstance, boundary RuntimeBoundary) error {
	provider, err := r.providers.GetProvider(instance)
	if err != nil {
		return err
	}
	operationID := r.newOperationID()
	if err := r.observeBoundary(ctx, instance, operationID, boundary); err != nil {
		return err
	}
	if err := provider.DeleteInstance(ctx, instance.InstanceID, instance.Name); err != nil && !errors.Is(err, backends.ErrInstanceNotFound) {
		observeErr := r.observeOperation(context.WithoutCancel(ctx), instance, operationID, OperationDeletion, OperationFailed)
		return errors.Join(err, observeErr)
	}
	return r.observeOperation(context.WithoutCancel(ctx), instance, operationID, OperationDeletion, OperationCompleted)
}

// newOperationID correlates one provider operation's observations. Without an
// observer nothing needs correlating, so no identity is minted.
func (r *ProviderRuntime) newOperationID() string {
	if r.observer == nil {
		return ""
	}
	return uuid.NewString()
}

func (r *ProviderRuntime) observeOperation(ctx context.Context, instance *models.MCPServerInstance, operationID string, operation OperationKind, phase OperationPhase) error {
	if r.observer == nil {
		return nil
	}
	return r.observer.Operation(ctx, RuntimeOperation{
		Resource:    ResourceRef{InstanceID: instance.InstanceID, WorkspaceID: instance.WorkspaceID},
		OperationID: operationID, Operation: operation, Phase: phase, ObservedAt: time.Now().UTC(),
	})
}

func (r *ProviderRuntime) observeBoundary(ctx context.Context, instance *models.MCPServerInstance, operationID string, boundary RuntimeBoundary) error {
	if r.observer == nil {
		return nil
	}
	return r.observer.Boundary(ctx, BoundaryObservation{
		Resource:    ResourceRef{InstanceID: instance.InstanceID, WorkspaceID: instance.WorkspaceID},
		OperationID: operationID, Boundary: boundary,
	})
}

func runtimeStatusReady(status string) bool {
	switch strings.ToLower(status) {
	case "running", "healthy", "ready":
		return true
	default:
		return false
	}
}

// runtimeStatusStopped reports a workload that has stopped for good: it
// exited, or its backend marked it failed. Waiting will not make it ready.
func runtimeStatusStopped(status string) bool {
	switch strings.ToLower(status) {
	case "stopped", "exited", "dead", "error", "failed":
		return true
	default:
		return false
	}
}

func safeStartupState(status string) string {
	switch state := strings.ToLower(strings.TrimSpace(status)); state {
	case "created", "creating", "pending", "running", "healthy", "ready",
		"stopped", "exited", "dead", "error", "failed", "restarting", "paused":
		return state
	default:
		return ""
	}
}

func startupReadinessFailureReason(timeout time.Duration, lastState string) string {
	reason := fmt.Sprintf("workload did not become ready within %s", timeout)
	if state := safeStartupState(lastState); state != "" {
		return fmt.Sprintf("%s (last state: %s)", reason, state)
	}
	return reason
}
