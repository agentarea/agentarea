// Package mcpgateway owns the demand boundary for container-backed MCP
// instances. Callers send ordinary Streamable HTTP; this package serializes
// cold starts, observes live requests, renews request leases, and reaps idle
// workloads without exposing lifecycle mechanics to Python. URL instances pass
// through the same boundary with no lifecycle, so their credentials stay here.
package mcpgateway

import (
	"bytes"
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/egress"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/secrets"
	"github.com/google/uuid"
)

// StartingHeader marks the gateway's own "workload is starting" 503. A request
// answered with it never reached the workload, so a client can repeat it, even
// a tools/call, without running the tool twice. A 503 that the workload or a
// remote server sends does not carry it.
const StartingHeader = "X-AgentArea-MCP-Starting"

// StartFailureHeader carries a classified startup failure without exposing
// workload output.
const StartFailureHeader = "X-AgentArea-MCP-Start-Failure"

// maxRequestBodyBytes bounds the request body the gateway buffers before it
// waits for a workload. MCP requests are JSON-RPC messages; tool arguments that
// carry files are the large ones.
const maxRequestBodyBytes = 32 << 20

type InstanceRuntime interface {
	EnsureReady(context.Context, *models.MCPServerInstance) (string, error)
	Delete(context.Context, *models.MCPServerInstance) error
}

type LifecycleRepository interface {
	WithInstanceLock(context.Context, string, func(context.Context) error) error
	LoadTarget(context.Context, string) (Target, error)
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
	leaseTTL, err := requiredDuration("AGENTAREA_MCP_LEASE_TTL", false)
	if err != nil {
		return Policy{}, err
	}
	startupTimeout, err := requiredDuration("AGENTAREA_MCP_STARTUP_TIMEOUT", false)
	if err != nil {
		return Policy{}, err
	}
	idleTimeout, err := requiredDuration("AGENTAREA_MCP_IDLE_TIMEOUT", true)
	if err != nil {
		return Policy{}, err
	}
	sweepInterval, err := requiredDuration("AGENTAREA_MCP_SWEEP_INTERVAL", false)
	if err != nil {
		return Policy{}, err
	}
	policy := Policy{
		RequestLeaseTTL: leaseTTL,
		StartupTimeout:  startupTimeout,
		IdleTimeout:     idleTimeout,
		SweepInterval:   sweepInterval,
		AuthSecret:      os.Getenv("AGENTAREA_MCP_GATEWAY_SECRET"),
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

// URLUpstream reaches url-transport instances: their secret headers come from
// the secret store and their member-chosen hosts are dialed under the egress
// policy.
type URLUpstream struct {
	Secrets secrets.SecretResolver
	Egress  egress.Policy
}

type Gateway struct {
	repository   LifecycleRepository
	runtime      InstanceRuntime
	policy       Policy
	logger       *slog.Logger
	remote       *RemoteUpstream
	requests     RequestObserver
	telemetry    *Telemetry
	urlSecrets   secrets.SecretResolver
	urlTransport http.RoundTripper
}

func New(repository LifecycleRepository, runtime InstanceRuntime, policy Policy, logger *slog.Logger, remote *RemoteUpstream, urls URLUpstream) (*Gateway, error) {
	if repository == nil || runtime == nil || logger == nil {
		return nil, fmt.Errorf("MCP gateway repository, runtime, and logger are required")
	}
	if err := policy.Validate(); err != nil {
		return nil, err
	}
	if remote != nil && (remote.BaseURL == "" || remote.Token == "") {
		return nil, fmt.Errorf("a remote MCP upstream requires both a base URL and a token")
	}
	if urls.Secrets == nil { // pragma: allowlist secret
		return nil, fmt.Errorf("MCP gateway requires a secret resolver for URL instances")
	}
	return &Gateway{
		repository: repository, runtime: runtime, policy: policy, logger: logger, remote: remote,
		urlSecrets: urls.Secrets, urlTransport: urls.Egress.Transport(),
	}, nil
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

// headerValue keeps the difference between an absent header and an empty one:
// 2025-era requests carry no MCP routing headers at all.
func headerValue(request *http.Request, name string) *string {
	if values := request.Header.Values(name); len(values) > 0 {
		value := values[0]
		return &value
	}
	return nil
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

	// A cold start holds this request for as long as the workload takes to
	// listen, and the server's read deadline runs out long before an npx
	// install finishes. Reading the body now, not when the request is finally
	// proxied, keeps a slow start from failing the request with an i/o timeout.
	if request.Body != nil && request.Body != http.NoBody {
		body, err := io.ReadAll(http.MaxBytesReader(response, request.Body, maxRequestBodyBytes))
		if err != nil {
			var tooLarge *http.MaxBytesError
			if errors.As(err, &tooLarge) {
				g.telemetry.rejected(request.Context(), headerValue(request, "Mcp-Method"), http.StatusRequestEntityTooLarge)
				http.Error(response, "MCP request body is too large", http.StatusRequestEntityTooLarge)
				return
			}
			g.telemetry.rejected(request.Context(), headerValue(request, "Mcp-Method"), http.StatusBadRequest)
			http.Error(response, "MCP request body could not be read", http.StatusBadRequest)
			return
		}
		request.Body = io.NopCloser(bytes.NewReader(body))
		request.ContentLength = int64(len(body))
		request.TransferEncoding = nil
	}

	requestID := uuid.NewString()
	var startedAt, endedAt time.Time
	var answer GatewayAnswer
	var coldStart *ColdStart
	if g.requests != nil {
		startedAt = time.Now()
	}
	loaded, err := g.repository.LoadTarget(request.Context(), instanceID)
	if err != nil {
		g.telemetry.rejected(request.Context(), headerValue(request, "Mcp-Method"), http.StatusBadGateway)
		http.Error(response, "MCP instance is unavailable", http.StatusBadGateway)
		return
	}
	if g.requests != nil {
		started := RequestStarted{
			RequestID: requestID, InstanceID: loaded.InstanceID, WorkspaceID: loaded.WorkspaceID,
			Method: request.Method, MCPMethod: headerValue(request, "Mcp-Method"), MCPName: headerValue(request, "Mcp-Name"),
			StartedAt: startedAt,
		}
		if err := g.requests.Started(request.Context(), started); err != nil {
			g.logRequestObserverFailure("started", started, err)
			g.telemetry.rejected(request.Context(), started.MCPMethod, http.StatusServiceUnavailable)
			http.Error(response, "MCP request processing unavailable", http.StatusServiceUnavailable)
			return
		}
		observed := &statusResponseWriter{ResponseWriter: response}
		response = observed
		defer func() {
			// A proxy panic (including a failed stream copy) is not a known
			// completion. Keep the start visible to the observers rather than
			// fabricate an end; only the gateway's own metrics close it.
			if value := recover(); value != nil {
				g.telemetry.aborted(context.WithoutCancel(request.Context()), started, coldStart != nil)
				panic(value)
			}
			if endedAt.IsZero() {
				endedAt = time.Now()
			}
			completed := RequestCompleted{
				RequestStarted: started, EndedAt: endedAt,
				StatusCode: observed.status, Canceled: request.Context().Err() != nil,
				Answer: answer, ColdStart: coldStart,
			}
			if err := g.requests.Completed(context.WithoutCancel(request.Context()), completed); err != nil {
				g.logRequestObserverFailure("completed", started, err)
			}
		}()
	}
	if loaded.URL != nil {
		g.serveURL(response, request, instanceID, loaded.URL)
		return
	}
	instance := loaded.Container
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
	report := &ColdStart{}
	startCtx, cancelStart := context.WithTimeout(
		withColdStart(context.WithoutCancel(request.Context()), report), g.policy.StartupTimeout,
	)
	err = g.repository.WithInstanceLock(startCtx, instanceID, func(lockCtx context.Context) error {
		defer func(began time.Time) { report.Total = time.Since(began) }(time.Now())
		// The desired instance was resolved before waiting for the lifecycle
		// lock so concurrent callers also retain an independent request fact.
		if err := g.repository.MarkStarting(lockCtx, instanceID); err != nil {
			return err
		}
		upstream, err = g.runtime.EnsureReady(lockCtx, instance)
		if err != nil {
			failureCtx, cancel := context.WithTimeout(context.WithoutCancel(lockCtx), 10*time.Second)
			defer cancel()
			if markErr := g.repository.MarkFailed(failureCtx, instanceID, err); markErr != nil {
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
			report.fail(stepAdmission)
			failureCtx, cancel := context.WithTimeout(context.WithoutCancel(lockCtx), 10*time.Second)
			defer cancel()
			cleanupErr := g.runtime.Delete(failureCtx, instance)
			markErr := g.repository.MarkFailed(failureCtx, instanceID, err)
			return errors.Join(err, cleanupErr, markErr)
		}
		return nil
	})
	cancelStart()
	coldStart = report.settle(err)
	if errors.Is(err, ErrStartInProgress) {
		// Another caller holds the lifecycle and is bringing this workload up.
		// Answering "unavailable" would be wrong twice over: nothing failed, and
		// the start this caller wanted is already running. Ask it to come back
		// instead — that retry is what completes the cold start.
		answer = AnswerStarting
		response.Header().Set("Retry-After", "1")
		response.Header().Set(StartingHeader, "1")
		http.Error(response, "MCP instance is starting", http.StatusServiceUnavailable)
		return
	}
	if err != nil {
		answer = AnswerStartFailed
		g.writeDemandFailure(response, instanceID, err)
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
	defer func() {
		endedAt = time.Now()
		close(stopHeartbeat)
		heartbeatErr := <-heartbeatDone
		cancelProxy()
		if heartbeatErr != nil && !errors.Is(heartbeatErr, context.Canceled) {
			g.logger.Error("MCP request lease heartbeat failed", slog.String("instance_id", instanceID), slog.String("request_id", requestID), slog.String("error", heartbeatErr.Error()))
		}
		g.finishRequest(instanceID, requestID)
	}()

	proxy := &httputil.ReverseProxy{
		FlushInterval: -1,
		Rewrite: func(outbound *httputil.ProxyRequest) {
			outbound.SetURL(target)
			outbound.SetXForwarded()
			outbound.Out.URL.Path = target.Path
			outbound.Out.URL.RawPath = ""
			if remoteHop {
				// Set, never add: whatever the caller sent is replaced, so a client
				// can neither read this credential nor smuggle its own to the data
				// plane. The header exists only on this outgoing request.
				outbound.Out.Header.Set("Authorization", "Bearer "+g.remote.Token)
			}
		},
		ModifyResponse: func(upstreamResponse *http.Response) error {
			// These markers are owned by the gateway and must never be spoofed
			// by an MCP workload response.
			upstreamResponse.Header.Del(StartingHeader)
			upstreamResponse.Header.Del(StartFailureHeader)
			g.observeUpstream(upstreamResponse, coldStart != nil, instanceID, requestID)
			return nil
		},
		ErrorHandler: func(writer http.ResponseWriter, _ *http.Request, proxyErr error) {
			g.telemetry.upstreamAnswered(request.Context(), 0)
			g.logger.Warn("MCP upstream request failed", slog.String("instance_id", instanceID), slog.String("error", proxyErr.Error()))
			http.Error(writer, "MCP upstream request failed", http.StatusBadGateway)
		},
	}
	proxy.ServeHTTP(response, request.WithContext(proxyCtx))

}

// refusedBodyLimit bounds the response body a refused first request reads;
// refusedLogLimit bounds what of it reaches the log.
const (
	refusedBodyLimit = 2048
	refusedLogLimit  = 256
)

// observeUpstream counts a workload response and warns when a workload
// answers the request that started it with a 4xx: a fresh workload that
// refuses a request the previous one accepted is otherwise invisible. The
// body read is put back so the caller still receives all of it.
func (g *Gateway) observeUpstream(response *http.Response, cold bool, instanceID, requestID string) {
	g.telemetry.upstreamAnswered(response.Request.Context(), response.StatusCode)
	if !cold || response.StatusCode < 400 || response.StatusCode > 499 {
		return
	}
	snippet, err := io.ReadAll(io.LimitReader(response.Body, refusedBodyLimit))
	response.Body = struct {
		io.Reader
		io.Closer
	}{io.MultiReader(bytes.NewReader(snippet), response.Body), response.Body}
	attrs := append([]any{
		slog.String("instance_id", instanceID), slog.String("request_id", requestID),
		slog.Int("status", response.StatusCode), slog.String("mcp_method", response.Request.Header.Get("Mcp-Method")),
	}, refusalDetail(snippet)...)
	if err != nil {
		attrs = append(attrs, slog.String("body_error", err.Error()))
	}
	g.logger.Warn("MCP workload refused the first request after its cold start", attrs...)
}

// refusalDetail is what a refused request logs of the response body: the
// JSON-RPC error code and message when the body is a JSON-RPC error, else its
// first bytes. Error bodies echo tool arguments, so neither is logged whole.
func refusalDetail(body []byte) []any {
	var message struct {
		JSONRPC string `json:"jsonrpc"`
		Error   *struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if json.Unmarshal(body, &message) == nil && message.JSONRPC == "2.0" && message.Error != nil {
		return []any{
			slog.Int("rpc_error_code", message.Error.Code),
			slog.String("rpc_error_message", truncate(message.Error.Message, refusedLogLimit)),
		}
	}
	return []any{slog.String("body", truncate(string(body), refusedLogLimit))}
}

func truncate(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return strings.ToValidUTF8(value[:limit], "")
}

func (g *Gateway) writeDemandFailure(response http.ResponseWriter, instanceID string, err error) {
	g.logger.Warn("MCP demand could not be satisfied", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
	reason, retryAfter, classified := startupFailureDetails(err)
	if !classified {
		response.Header().Set("Retry-After", "5")
		http.Error(response, "MCP instance is unavailable", http.StatusBadGateway)
		return
	}
	response.Header().Set(StartFailureHeader, reason)
	response.Header().Set("Retry-After", fmt.Sprintf("%d", retryAfter))
	http.Error(response, "MCP workload failed during startup: "+reason, http.StatusServiceUnavailable)
}

func startupFailureDetails(err error) (string, int, bool) {
	var classified failureReasonError
	if !errors.As(err, &classified) {
		return "", 0, false
	}
	reason := strings.TrimSpace(strings.NewReplacer("\r", " ", "\n", " ").Replace(classified.FailureReason()))
	if reason == "" {
		return "", 0, false
	}
	return reason, retryAfterSeconds(err), true
}

func retryAfterSeconds(err error) int {
	var retryable retryDelayError
	if !errors.As(err, &retryable) {
		return 1
	}
	delay := retryable.RetryDelay()
	if delay <= 0 {
		return 1
	}
	seconds := int(delay / time.Second)
	if delay%time.Second != 0 {
		seconds++
	}
	if seconds < 1 {
		return 1
	}
	return seconds
}

// statusResponseWriter records the final status only. Unwrap lets net/http's
// ResponseController retain flushing and hijacking capabilities without
// buffering either request or response bodies.
type statusResponseWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusResponseWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

func (w *statusResponseWriter) WriteHeader(status int) {
	if w.status == 0 && (status >= 200 || status == http.StatusSwitchingProtocols) {
		w.status = status
	}
	w.ResponseWriter.WriteHeader(status)
}

func (w *statusResponseWriter) Write(body []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(http.StatusOK)
	}
	return w.ResponseWriter.Write(body)
}

func (g *Gateway) logRequestObserverFailure(phase string, request RequestStarted, err error) {
	g.logger.Error("MCP request observer failed",
		slog.String("phase", phase),
		slog.String("request_id", request.RequestID),
		slog.String("instance_id", request.InstanceID),
		slog.String("workspace_id", request.WorkspaceID),
		slog.String("error", err.Error()))
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
		case errors.Is(err, ErrStartInProgress):
			response.Header().Set("Retry-After", "5")
			http.Error(response, "MCP instance is starting", http.StatusConflict)
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
		if errors.Is(err, ErrStartInProgress) {
			// The candidate went from idle to starting between the query and the
			// lock. It is no longer eligible, and the next sweep will see the
			// truth; the sweep did its job.
			continue
		}
		if err != nil {
			g.logger.Warn("Failed to reap idle MCP instance", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
			continue
		}
		if removed {
			reaped++
			g.telemetry.reaped(ctx)
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
