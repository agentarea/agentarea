package mcpgateway

import (
	"context"
	"errors"
	"fmt"
	"strings"
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

type ProviderRuntime struct {
	providers      ProviderSelector
	backend        backends.Backend
	config         *config.Config
	startupTimeout time.Duration
	remote         *RemoteUpstream
	observer       RuntimeObserver
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
	}, nil
}

func (r *ProviderRuntime) EnsureReady(ctx context.Context, instance *models.MCPServerInstance) (string, error) {
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
		// A stopped workload never becomes ready again — mcp-base exits when
		// its stdio server dies — so it is replaced, not waited on until the
		// startup timeout gives up on it.
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
			observeErr := r.observeOperation(context.WithoutCancel(ctx), instance, operationID, OperationCreation, OperationFailed)
			boundaryErr := r.observeBoundary(context.WithoutCancel(ctx), instance, operationID, BoundaryCreationFailed)
			return "", errors.Join(err, observeErr, boundaryErr)
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
			return "", err
		}
	}
	// A started container reports running before its server listens; waiting
	// here turns that window into a longer first request instead of a
	// connection-refused 502. A remote data plane does the same wait itself.
	if activating && r.remote == nil && status != nil && status.InternalURL != "" {
		if err := r.awaitListening(ctx, instance, status.InternalURL, startDeadline); err != nil {
			return "", r.cleanupFailedStart(instance, fmt.Errorf("MCP instance never listened: %w", err))
		}
	}
	if activating {
		if err := r.observeBoundary(context.WithoutCancel(ctx), instance, operationID, BoundaryActivation); err != nil {
			return "", r.cleanupFailedStart(instance, err)
		}
	}

	return r.upstreamURL(instance, instanceType)
}

// awaitRunning polls the backend until the workload reports running, within
// the startup timeout. A wait that fails tears the workload down.
func (r *ProviderRuntime) awaitRunning(ctx context.Context, instance *models.MCPServerInstance) (*backends.InstanceStatus, error) {
	deadline := time.NewTimer(r.startupTimeout)
	defer deadline.Stop()
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	for {
		status, statusErr := r.backend.GetInstanceStatus(ctx, instance.InstanceID)
		if statusErr == nil && runtimeStatusReady(status.Status) {
			return status, nil
		}
		if statusErr != nil && !errors.Is(statusErr, backends.ErrInstanceNotFound) {
			return nil, r.cleanupFailedStart(instance, fmt.Errorf("inspect MCP runtime while starting: %w", statusErr))
		}
		if statusErr == nil && runtimeStatusStopped(status.Status) {
			return nil, r.cleanupFailedStart(instance, fmt.Errorf("MCP workload stopped while starting (state %q)", status.Status))
		}
		select {
		case <-ctx.Done():
			// The gateway allows a start exactly StartupTimeout, which is
			// also this loop's deadline, so this branch — not the timer
			// below — is the one production takes. Report the same last
			// state the timer would: without it the log says only that time
			// ran out, and the workload has already been cleaned up by the
			// time anyone could go and look at it.
			if statusErr != nil {
				return nil, r.cleanupFailedStart(instance,
					fmt.Errorf("MCP instance did not become ready: %w", errors.Join(ctx.Err(), statusErr)))
			}
			return nil, r.cleanupFailedStart(instance,
				fmt.Errorf("MCP instance did not become ready; last state %q: %w", status.Status, ctx.Err()))
		case <-deadline.C:
			if statusErr != nil {
				return nil, r.cleanupFailedStart(instance, fmt.Errorf("MCP instance did not become ready: %w", statusErr))
			}
			return nil, r.cleanupFailedStart(instance, fmt.Errorf("MCP instance did not become ready; last state %q", status.Status))
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
				cancel(fmt.Errorf("the workload stopped (state %q)", status.Status))
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
		return errors.Join(cause, fmt.Errorf("cleanup failed MCP activation: %w", err))
	}
	return cause
}

func (r *ProviderRuntime) Delete(ctx context.Context, instance *models.MCPServerInstance) error {
	return r.delete(ctx, instance, BoundaryDeletion)
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
