// Package mcpgateway owns the demand boundary for container-backed MCP
// instances. Callers send ordinary Streamable HTTP; this package serializes
// cold starts, observes live requests, renews request leases, and reaps idle
// workloads without exposing lifecycle mechanics to Python.
package mcpgateway

import (
	"context"
	"crypto/subtle"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/google/uuid"
)

type InstanceRuntime interface {
	EnsureReady(context.Context, *models.MCPServerInstance) (string, error)
	Delete(context.Context, *models.MCPServerInstance) error
}

type LifecycleRepository interface {
	WithInstanceLock(context.Context, string, func(context.Context) error) error
	LoadInstance(context.Context, string) (*models.MCPServerInstance, error)
	MarkStarting(context.Context, string) error
	MarkFailed(context.Context, string, error) error
	MarkReadyAndBeginRequest(context.Context, string, string, time.Duration) error
	HeartbeatRequest(context.Context, string, time.Duration) error
	FinishRequest(context.Context, string, string) error
	IdleCandidates(context.Context, time.Duration) ([]string, error)
	ReapIfIdle(context.Context, string, time.Duration, func(context.Context, *models.MCPServerInstance) error) (bool, error)
	RetireForDeletion(context.Context, string, func(context.Context, *models.MCPServerInstance) error) error
}

type Policy struct {
	RequestLeaseTTL time.Duration
	StartupTimeout  time.Duration
	IdleTimeout     time.Duration
	SweepInterval   time.Duration
	AuthSecret      string
}

func LoadPolicyFromEnv() (Policy, error) {
	leaseTTL, err := requiredDuration("MCP_REQUEST_LEASE_TTL", false)
	if err != nil {
		return Policy{}, err
	}
	startupTimeout, err := requiredDuration("MCP_GATEWAY_STARTUP_TIMEOUT", false)
	if err != nil {
		return Policy{}, err
	}
	idleTimeout, err := requiredDuration("MCP_IDLE_TIMEOUT", true)
	if err != nil {
		return Policy{}, err
	}
	sweepInterval, err := requiredDuration("MCP_IDLE_SWEEP_INTERVAL", false)
	if err != nil {
		return Policy{}, err
	}
	policy := Policy{
		RequestLeaseTTL: leaseTTL,
		StartupTimeout:  startupTimeout,
		IdleTimeout:     idleTimeout,
		SweepInterval:   sweepInterval,
		AuthSecret:      os.Getenv("MCP_GATEWAY_AUTH_SECRET"),
	}
	if err := policy.Validate(); err != nil {
		return Policy{}, err
	}
	return policy, nil
}

func requiredDuration(name string, allowZero bool) (time.Duration, error) {
	raw := os.Getenv(name)
	if raw == "" {
		return 0, fmt.Errorf("%s is required", name)
	}
	value, err := time.ParseDuration(raw)
	if err != nil {
		return 0, fmt.Errorf("%s must be a duration: %w", name, err)
	}
	if value < 0 || (!allowZero && value == 0) {
		return 0, fmt.Errorf("%s must be %s", name, map[bool]string{true: "non-negative", false: "positive"}[allowZero])
	}
	return value, nil
}

func (p Policy) Validate() error {
	if p.RequestLeaseTTL <= 0 || p.StartupTimeout <= 0 {
		return fmt.Errorf("MCP gateway request lease and startup timeout must be positive")
	}
	if p.IdleTimeout < 0 || p.SweepInterval <= 0 {
		return fmt.Errorf("MCP gateway idle timeout must be non-negative and sweep interval positive")
	}
	if len(p.AuthSecret) < 32 {
		return fmt.Errorf("MCP gateway auth secret must contain at least 32 bytes")
	}
	return nil
}

type Gateway struct {
	repository LifecycleRepository
	runtime    InstanceRuntime
	policy     Policy
	logger     *slog.Logger
	remote     *RemoteUpstream
	connector  *ConnectorUpstream
}

func New(repository LifecycleRepository, runtime InstanceRuntime, policy Policy, logger *slog.Logger, remote *RemoteUpstream, connector ...*ConnectorUpstream) (*Gateway, error) {
	if repository == nil || runtime == nil || logger == nil {
		return nil, fmt.Errorf("MCP gateway repository, runtime, and logger are required")
	}
	if err := policy.Validate(); err != nil {
		return nil, err
	}
	if remote != nil && (remote.BaseURL == "" || remote.Token == "") {
		return nil, fmt.Errorf("a remote MCP upstream requires both a base URL and a token")
	}
	if len(connector) > 1 {
		return nil, fmt.Errorf("at most one connector MCP upstream is allowed")
	}
	var connectorUpstream *ConnectorUpstream
	if len(connector) == 1 {
		connectorUpstream = connector[0]
		if !connectorUpstream.valid() {
			return nil, fmt.Errorf("connector MCP upstream requires a logical data plane ID and transport")
		}
	}
	if remote != nil && connectorUpstream != nil {
		return nil, fmt.Errorf("remote and connector MCP upstreams are mutually exclusive")
	}
	return &Gateway{repository: repository, runtime: runtime, policy: policy, logger: logger, remote: remote, connector: connectorUpstream}, nil
}

// isRemoteUpstream reports whether this upstream is the configured data plane,
// which is the only destination allowed to receive the machine credential.
//
// Origin and path prefix must both match: an upstream that names any other host,
// or the right host by some other route, is proxied without the credential
// rather than handed one it should never see.
func (g *Gateway) isRemoteUpstream(target *url.URL, parseErr error) bool {
	if g.remote == nil || parseErr != nil || target == nil {
		return false
	}
	base, err := url.Parse(g.remote.BaseURL)
	if err != nil || base.Host == "" {
		return false
	}
	if target.Scheme != base.Scheme || target.Host != base.Host {
		return false
	}
	prefix := strings.TrimRight(base.Path, "/") + "/dataplane/v1/instances/"
	return strings.HasPrefix(target.Path, prefix)
}

func (g *Gateway) ServeHTTP(response http.ResponseWriter, request *http.Request) {
	instanceID, err := instanceIDFromPath(request.URL.Path)
	if err != nil {
		http.Error(response, err.Error(), http.StatusNotFound)
		return
	}
	if !g.authorized(request.Header.Get("X-AgentArea-Manager-Authorization")) {
		http.Error(response, "unauthorized", http.StatusUnauthorized)
		return
	}
	request.Header.Del("X-AgentArea-Manager-Authorization")

	requestID := uuid.NewString()
	var upstream string
	// The start is deliberately detached from the caller's request. A client
	// abandoning one HTTP request is not a statement that the workload is
	// unwanted — lazy start means it retries, and the next attempt wants the
	// workload this one is bringing up. While the start inherited
	// request.Context(), an abandoned request cancelled it and the runtime tore
	// down the Deployment it had just created; with a caller timeout shorter
	// than the readiness probe's first success — verification allows 5s, the
	// probe cannot report ready before ~8s — every attempt created and deleted a
	// workload and container-backed MCP could never come up at all.
	// StartupTimeout is now the only bound on a cold start.
	startCtx, cancelStart := context.WithTimeout(
		context.WithoutCancel(request.Context()), g.policy.StartupTimeout,
	)
	err = g.repository.WithInstanceLock(startCtx, instanceID, func(lockCtx context.Context) error {
		instance, loadErr := g.repository.LoadInstance(lockCtx, instanceID)
		if loadErr != nil {
			return loadErr
		}
		if err := g.repository.MarkStarting(lockCtx, instanceID); err != nil {
			return err
		}
		upstream, err = g.runtime.EnsureReady(lockCtx, instance)
		if err != nil {
			if markErr := g.repository.MarkFailed(lockCtx, instanceID, err); markErr != nil {
				// Leaves the row in 'starting'; the idle sweep reclaims it, but
				// the operator should see why the state is inaccurate.
				g.logger.Error("could not record MCP start failure",
					slog.String("instance_id", instanceID),
					slog.String("error", markErr.Error()))
			}
			return err
		}
		if err := g.repository.MarkReadyAndBeginRequest(
			lockCtx, instanceID, requestID, g.policy.RequestLeaseTTL,
		); err != nil {
			cleanupErr := g.runtime.Delete(lockCtx, instance)
			_ = g.repository.MarkFailed(lockCtx, instanceID, err)
			return errors.Join(err, cleanupErr)
		}
		return nil
	})
	cancelStart()
	if err != nil {
		g.logger.Warn("MCP demand could not be satisfied", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
		response.Header().Set("Retry-After", "5")
		http.Error(response, "MCP instance is unavailable", http.StatusBadGateway)
		return
	}

	target, err := url.Parse(upstream)
	remoteHop := g.isRemoteUpstream(target, err)
	// In-cluster workloads are plain http. The data-plane hop leaves this
	// network, so it must be https unless the operator declared the path
	// private, which the data-plane client validates at startup.
	allowedScheme := target != nil && (target.Scheme == "http" || (remoteHop && target.Scheme == "https"))
	if err != nil || !allowedScheme || target.Host == "" {
		g.finishRequest(instanceID, requestID)
		http.Error(response, "MCP runtime returned an invalid internal endpoint", http.StatusBadGateway)
		return
	}

	proxyCtx, cancelProxy := context.WithCancel(request.Context())
	stopHeartbeat := make(chan struct{})
	heartbeatDone := make(chan error, 1)
	go g.heartbeat(proxyCtx, cancelProxy, requestID, stopHeartbeat, heartbeatDone)

	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.FlushInterval = -1
	if g.connector != nil {
		proxy.Transport = g.connector.ConnectorTransport
	}
	originalDirector := proxy.Director
	proxy.Director = func(outbound *http.Request) {
		originalDirector(outbound)
		outbound.URL.Path = target.Path
		outbound.URL.RawPath = ""
		outbound.Host = target.Host
		if g.connector != nil {
			// The connector agent needs the selected instance, but the caller
			// never controls this routing header.
			outbound.Header.Set("X-Agentarea-Instance-Id", instanceID)
		}
		if remoteHop {
			// Set, never add: whatever the caller sent is replaced, so a client
			// can neither read this credential nor smuggle its own to the data
			// plane. The header exists only on this outgoing request.
			outbound.Header.Set("Authorization", "Bearer "+g.remote.Token)
		}
	}
	proxy.ErrorHandler = func(writer http.ResponseWriter, _ *http.Request, proxyErr error) {
		g.logger.Warn("MCP upstream request failed", slog.String("instance_id", instanceID), slog.String("error", proxyErr.Error()))
		http.Error(writer, "MCP upstream request failed", http.StatusBadGateway)
	}
	proxy.ServeHTTP(response, request.WithContext(proxyCtx))

	close(stopHeartbeat)
	heartbeatErr := <-heartbeatDone
	cancelProxy()
	if heartbeatErr != nil && !errors.Is(heartbeatErr, context.Canceled) {
		g.logger.Error("MCP request lease heartbeat failed", slog.String("instance_id", instanceID), slog.String("request_id", requestID), slog.String("error", heartbeatErr.Error()))
	}
	g.finishRequest(instanceID, requestID)
}

// RetireHTTP synchronously removes the data-plane workload before desired
// state is deleted. The operation is idempotent and refuses to race an active
// request lease, so callers can safely retry a lost response.
func (g *Gateway) RetireHTTP(response http.ResponseWriter, request *http.Request) {
	instanceID, err := instanceIDFromRetirePath(request.URL.Path)
	if err != nil {
		http.Error(response, err.Error(), http.StatusNotFound)
		return
	}
	if !g.authorized(request.Header.Get("X-AgentArea-Manager-Authorization")) {
		http.Error(response, "unauthorized", http.StatusUnauthorized)
		return
	}
	request.Header.Del("X-AgentArea-Manager-Authorization")

	if err := g.repository.RetireForDeletion(request.Context(), instanceID, g.runtime.Delete); err != nil {
		switch {
		case errors.Is(err, ErrInstanceBusy):
			response.Header().Set("Retry-After", "5")
			http.Error(response, "MCP instance has active requests", http.StatusConflict)
		case errors.Is(err, ErrInstanceNotFound):
			http.Error(response, "MCP instance not found", http.StatusNotFound)
		default:
			g.logger.Error("MCP workload retirement failed", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
			response.Header().Set("Retry-After", "5")
			http.Error(response, "MCP instance retirement failed", http.StatusBadGateway)
		}
		return
	}
	response.WriteHeader(http.StatusNoContent)
}

func (g *Gateway) authorized(value string) bool {
	presented, ok := strings.CutPrefix(value, "Bearer ")
	if !ok || len(presented) != len(g.policy.AuthSecret) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(presented), []byte(g.policy.AuthSecret)) == 1
}

func (g *Gateway) heartbeat(ctx context.Context, cancel context.CancelFunc, requestID string, stop <-chan struct{}, done chan<- error) {
	interval := g.policy.RequestLeaseTTL / 3
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-stop:
			done <- nil
			return
		case <-ctx.Done():
			done <- ctx.Err()
			return
		case <-ticker.C:
			if err := g.repository.HeartbeatRequest(ctx, requestID, g.policy.RequestLeaseTTL); err != nil {
				cancel()
				done <- err
				return
			}
		}
	}
}

func (g *Gateway) finishRequest(instanceID, requestID string) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := g.repository.FinishRequest(ctx, instanceID, requestID); err != nil {
		g.logger.Error("MCP request lease finalization failed", slog.String("instance_id", instanceID), slog.String("request_id", requestID), slog.String("error", err.Error()))
	}
}

func (g *Gateway) StartReaper(ctx context.Context) {
	if g.policy.IdleTimeout == 0 {
		g.logger.Info("MCP idle reaper disabled by explicit zero timeout")
		return
	}
	ticker := time.NewTicker(g.policy.SweepInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if _, err := g.Reap(ctx); err != nil {
				g.logger.Error("MCP idle sweep failed", slog.String("error", err.Error()))
			}
		}
	}
}

func (g *Gateway) Reap(ctx context.Context) (int, error) {
	ids, err := g.repository.IdleCandidates(ctx, g.policy.IdleTimeout)
	if err != nil {
		return 0, err
	}
	reaped := 0
	for _, instanceID := range ids {
		removed, err := g.repository.ReapIfIdle(ctx, instanceID, g.policy.IdleTimeout, g.runtime.Delete)
		if err != nil {
			g.logger.Warn("Failed to reap idle MCP instance", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
			continue
		}
		if removed {
			reaped++
		}
	}
	return reaped, nil
}

func instanceIDFromPath(value string) (string, error) {
	parts := strings.Split(strings.Trim(value, "/"), "/")
	if len(parts) != 3 || parts[0] != "mcp" || parts[2] != "mcp" {
		return "", fmt.Errorf("expected /mcp/{instance_id}/mcp")
	}
	parsed, err := uuid.Parse(parts[1])
	if err != nil {
		return "", fmt.Errorf("invalid MCP instance id")
	}
	return parsed.String(), nil
}

func instanceIDFromRetirePath(value string) (string, error) {
	parts := strings.Split(strings.Trim(value, "/"), "/")
	if len(parts) != 2 || parts[0] != "mcp" {
		return "", fmt.Errorf("expected /mcp/{instance_id}")
	}
	parsed, err := uuid.Parse(parts[1])
	if err != nil {
		return "", fmt.Errorf("invalid MCP instance id")
	}
	return parsed.String(), nil
}
