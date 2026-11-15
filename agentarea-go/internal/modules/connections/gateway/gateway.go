package gateway

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
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

const (
	maxRequestBodyBytes = 32 << 20
	refusedBodyLimit    = 2048
	refusalLogLimit     = 256
	finishTimeout       = 10 * time.Second
	minSecretLength     = 32
	managedByPlatform   = "platform"
)

// Options configure a Gateway.
type Options struct {
	Runtime Runtime
	// Secret is AGENTAREA_MCP_GATEWAY_SECRET: callers outside the process
	// present it in X-AgentArea-Manager-Authorization. Empty only for the
	// handler a process hands its own code, which is never mounted on a listener.
	Secret string
	// LeaseTTL is the request lease; the gateway renews it every third of it.
	LeaseTTL time.Duration
	// Workloads reaches the workloads (and the data plane); URLs reaches
	// member-chosen URL endpoints under the egress policy.
	Workloads http.RoundTripper
	URLs      http.RoundTripper
	Observer  RequestObserver
	Telemetry *Telemetry
	Log       *slog.Logger
}

// Gateway serves the MCP data path.
type Gateway struct {
	o Options
}

// New checks o. A Secret, when given, must be at least 32 bytes.
func New(o Options) (*Gateway, error) {
	switch {
	case o.Runtime == nil || o.Log == nil || o.Workloads == nil || o.URLs == nil:
		return nil, errors.New("MCP gateway needs a runtime, a logger and both transports")
	case o.LeaseTTL <= 0:
		return nil, errors.New("MCP gateway request lease must be positive")
	case o.Secret != "" && len(o.Secret) < minSecretLength:
		return nil, fmt.Errorf("MCP gateway secret must contain at least %d bytes", minSecretLength)
	}
	return &Gateway{o: o}, nil
}

// Routes registers the data path on mux.
func (g *Gateway) Routes(mux interface {
	Handle(pattern string, h http.Handler)
}) {
	mux.Handle("/mcp/{instance_id}/mcp", http.HandlerFunc(g.serveMCP))
	mux.Handle("DELETE /mcp/{instance_id}", http.HandlerFunc(g.serveRetire))
}

// ServeHTTP serves the data path without a mux of the caller's.
func (g *Gateway) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	mux := http.NewServeMux()
	g.Routes(mux)
	mux.ServeHTTP(w, r)
}

func (g *Gateway) authorized(r *http.Request) bool {
	if g.o.Secret == "" {
		return true
	}
	got, ok := strings.CutPrefix(r.Header.Get(AuthHeader), "Bearer ")
	return ok && subtle.ConstantTimeCompare([]byte(got), []byte(g.o.Secret)) == 1
}

func instanceID(r *http.Request) (string, error) {
	id, err := uuid.Parse(r.PathValue("instance_id"))
	if err != nil {
		return "", errors.New("MCP instance id must be a UUID")
	}
	return id.String(), nil
}

func headerValue(r *http.Request, name string) *string {
	if v := r.Header.Get(name); v != "" {
		return &v
	}
	return nil
}

func (g *Gateway) serveRetire(w http.ResponseWriter, r *http.Request) {
	id, err := instanceID(r)
	if err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}
	if !g.authorized(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	err = g.o.Runtime.Retire(r.Context(), id)
	switch {
	case err == nil:
		w.WriteHeader(http.StatusNoContent)
	case errors.Is(err, ErrInstanceNotFound):
		http.Error(w, "MCP instance not found", http.StatusNotFound)
	case errors.Is(err, ErrInstanceBusy), errors.Is(err, ErrStartInProgress):
		w.Header().Set("Retry-After", "5")
		http.Error(w, "MCP instance is in use", http.StatusConflict)
	default:
		g.o.Log.Error("MCP workload could not be retired", "instance_id", id, "error", err)
		w.Header().Set("Retry-After", "5")
		http.Error(w, "MCP workload could not be retired", http.StatusBadGateway)
	}
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(code int) {
	if w.status == 0 {
		w.status = code
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *statusWriter) Write(b []byte) (int, error) {
	if w.status == 0 {
		w.status = http.StatusOK
	}
	return w.ResponseWriter.Write(b)
}

func (w *statusWriter) Flush() {
	if f, ok := w.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func (w *statusWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

func (g *Gateway) serveMCP(w http.ResponseWriter, r *http.Request) {
	id, err := instanceID(r)
	if err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}
	if !g.authorized(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	r.Header.Del(AuthHeader)
	mcpMethod := headerValue(r, "Mcp-Method")
	// A cold start holds the request for as long as the workload takes to
	// listen; reading the body now keeps the server's read deadline from
	// failing a slow start.
	if r.Body != nil && r.Body != http.NoBody {
		body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, maxRequestBodyBytes))
		if err != nil {
			var tooLarge *http.MaxBytesError
			if errors.As(err, &tooLarge) {
				g.o.Telemetry.rejected(r.Context(), mcpMethod, http.StatusRequestEntityTooLarge)
				http.Error(w, "MCP request body is too large", http.StatusRequestEntityTooLarge)
				return
			}
			g.o.Telemetry.rejected(r.Context(), mcpMethod, http.StatusBadRequest)
			http.Error(w, "MCP request body could not be read", http.StatusBadRequest)
			return
		}
		r.Body = io.NopCloser(bytes.NewReader(body))
		r.ContentLength = int64(len(body))
		r.TransferEncoding = nil
	}

	requestID := uuid.NewString()
	startedAt := time.Now()
	target, err := g.o.Runtime.Load(r.Context(), id)
	if err != nil {
		g.o.Log.Error("MCP instance could not be loaded", "instance_id", id, "error", err)
		g.o.Telemetry.rejected(r.Context(), mcpMethod, http.StatusBadGateway)
		http.Error(w, "MCP instance is unavailable", http.StatusBadGateway)
		return
	}
	started := RequestStarted{
		RequestID: requestID, InstanceID: target.InstanceID, WorkspaceID: target.WorkspaceID,
		Method: r.Method, MCPMethod: mcpMethod, MCPName: headerValue(r, "Mcp-Name"), StartedAt: startedAt,
	}
	obs := g.observers()
	if err := obs.Started(r.Context(), started); err != nil {
		g.o.Log.Error("MCP request observer refused the request", "instance_id", id, "request_id", requestID, "error", err)
		g.o.Telemetry.rejected(r.Context(), mcpMethod, http.StatusServiceUnavailable)
		http.Error(w, "MCP request processing unavailable", http.StatusServiceUnavailable)
		return
	}
	sw := &statusWriter{ResponseWriter: w}
	var (
		endedAt   time.Time
		answer    Answer
		coldStart *ColdStart
	)
	defer func() {
		// A panic (a failed stream copy among them) is not a known completion:
		// the start stays visible to observers; only the metrics close it.
		if v := recover(); v != nil {
			g.o.Telemetry.aborted(context.WithoutCancel(r.Context()), started, coldStart != nil)
			panic(v)
		}
		if endedAt.IsZero() {
			endedAt = time.Now()
		}
		done := RequestCompleted{RequestStarted: started, EndedAt: endedAt, StatusCode: sw.status,
			Canceled: r.Context().Err() != nil, Answer: answer, ColdStart: coldStart}
		if err := obs.Completed(context.WithoutCancel(r.Context()), done); err != nil {
			g.o.Log.Error("MCP request observer failed on completion", "instance_id", id, "request_id", requestID, "error", err)
		}
	}()
	if target.URL != nil {
		g.serveURL(sw, r, target)
		return
	}

	// The start is detached from the caller: an abandoned request is not a
	// statement that the workload is unwanted, and the retry wants the
	// workload this one is bringing up. The startup timeout bounds it.
	report := &ColdStart{}
	adm, err := g.o.Runtime.Admit(context.WithoutCancel(r.Context()), target, requestID, report)
	coldStart = report.Settle(err)
	if errors.Is(err, ErrStartInProgress) {
		answer = AnswerStarting
		sw.Header().Set("Retry-After", "1")
		sw.Header().Set(StartingHeader, "1")
		http.Error(sw, "MCP instance is starting", http.StatusServiceUnavailable)
		return
	}
	if err != nil {
		answer = AnswerStartFailed
		g.writeDemandFailure(sw, id, err)
		return
	}
	upstream, err := url.Parse(adm.Upstream)
	allowed := err == nil && (upstream.Scheme == "http" || (adm.Remote && upstream.Scheme == "https")) && upstream.Host != ""
	if !allowed {
		g.finish(id, requestID, adm.Lease)
		http.Error(sw, "MCP runtime returned an invalid internal endpoint", http.StatusBadGateway)
		return
	}
	proxyCtx, cancelProxy := context.WithCancel(r.Context())
	stop := make(chan struct{})
	beat := make(chan error, 1)
	go g.heartbeat(proxyCtx, cancelProxy, adm.Lease, stop, beat)
	defer func() {
		endedAt = time.Now()
		close(stop)
		herr := <-beat
		cancelProxy()
		if herr != nil && !errors.Is(herr, context.Canceled) {
			g.o.Log.Error("MCP request lease heartbeat failed", "instance_id", id, "request_id", requestID, "error", herr)
		}
		g.finish(id, requestID, adm.Lease)
	}()
	cold := coldStart != nil
	proxy := &httputil.ReverseProxy{
		Transport:     g.o.Workloads,
		FlushInterval: -1,
		Rewrite: func(out *httputil.ProxyRequest) {
			out.SetURL(upstream)
			out.SetXForwarded()
			out.Out.URL.Path = upstream.Path
			out.Out.URL.RawPath = ""
			if adm.Remote && adm.Authorize != nil {
				adm.Authorize(out.Out)
			}
		},
		ModifyResponse: func(resp *http.Response) error {
			resp.Header.Del(StartingHeader)
			resp.Header.Del(StartFailureHeader)
			g.observeUpstream(resp, cold, id, requestID)
			return nil
		},
		ErrorHandler: func(rw http.ResponseWriter, _ *http.Request, perr error) {
			g.o.Telemetry.upstreamAnswered(r.Context(), 0)
			g.o.Log.Warn("MCP upstream request failed", "instance_id", id, "error", perr)
			http.Error(rw, "MCP upstream request failed", http.StatusBadGateway)
		},
	}
	proxy.ServeHTTP(sw, r.WithContext(proxyCtx))
}

func (g *Gateway) observers() RequestObserver {
	list := requestObservers{}
	if g.o.Observer != nil {
		list = append(list, g.o.Observer)
	}
	if g.o.Telemetry != nil {
		list = append(list, g.o.Telemetry)
	}
	return list
}

func (g *Gateway) heartbeat(ctx context.Context, cancel context.CancelFunc, lease Lease, stop <-chan struct{}, done chan<- error) {
	t := time.NewTicker(g.o.LeaseTTL / 3)
	defer t.Stop()
	for {
		select {
		case <-stop:
			done <- nil
			return
		case <-ctx.Done():
			done <- ctx.Err()
			return
		case <-t.C:
			if err := lease.Heartbeat(ctx); err != nil {
				cancel()
				done <- err
				return
			}
		}
	}
}

func (g *Gateway) finish(instanceID, requestID string, lease Lease) {
	ctx, cancel := context.WithTimeout(context.Background(), finishTimeout)
	defer cancel()
	if err := lease.Finish(ctx); err != nil {
		g.o.Log.Error("MCP request lease finalization failed", "instance_id", instanceID, "request_id", requestID, "error", err)
	}
}

func (g *Gateway) writeDemandFailure(w http.ResponseWriter, instanceID string, err error) {
	g.o.Log.Warn("MCP demand could not be satisfied", "instance_id", instanceID, "error", err)
	var failure StartFailure
	if !errors.As(err, &failure) || strings.TrimSpace(failure.FailureReason()) == "" {
		w.Header().Set("Retry-After", "5")
		http.Error(w, "MCP instance is unavailable", http.StatusBadGateway)
		return
	}
	reason := headerSafe(failure.FailureReason())
	w.Header().Set(StartFailureHeader, reason)
	w.Header().Set("Retry-After", strconv.Itoa(retryAfterSeconds(failure.RetryDelay())))
	http.Error(w, "MCP workload failed during startup: "+reason, http.StatusServiceUnavailable)
}

func retryAfterSeconds(d time.Duration) int {
	s := int((d + time.Second - 1) / time.Second)
	return max(s, 1)
}

// headerSafe keeps a reason a valid header value: printable ASCII only.
func headerSafe(s string) string {
	b := make([]byte, 0, len(s))
	for i := range len(s) {
		c := s[i]
		if c >= 0x20 && c < 0x7f {
			b = append(b, c)
		} else {
			b = append(b, '?')
		}
	}
	return string(b)
}

func (g *Gateway) observeUpstream(resp *http.Response, cold bool, instanceID, requestID string) {
	g.o.Telemetry.upstreamAnswered(resp.Request.Context(), resp.StatusCode)
	if !cold || resp.StatusCode < 400 || resp.StatusCode > 499 {
		return
	}
	snippet, err := io.ReadAll(io.LimitReader(resp.Body, refusedBodyLimit))
	resp.Body = struct {
		io.Reader
		io.Closer
	}{io.MultiReader(bytes.NewReader(snippet), resp.Body), resp.Body}
	attrs := append([]any{"instance_id", instanceID, "request_id", requestID, "status", resp.StatusCode,
		"mcp_method", resp.Request.Header.Get("Mcp-Method")}, refusalDetail(snippet)...)
	if err != nil {
		attrs = append(attrs, "body_error", err.Error())
	}
	g.o.Log.Warn("MCP workload refused the first request after its cold start", attrs...)
}

func refusalDetail(body []byte) []any {
	var rpc struct {
		Error *struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if json.Unmarshal(body, &rpc) == nil && rpc.Error != nil {
		return []any{"rpc_error_code", rpc.Error.Code, "rpc_error_message", truncate(rpc.Error.Message)}
	}
	return []any{"body", truncate(string(body))}
}

func truncate(s string) string {
	if len(s) <= refusalLogLimit {
		return s
	}
	return s[:refusalLogLimit]
}

func forwardedURLHeader(name string) bool {
	switch name {
	case "Accept", "Content-Type", "Last-Event-Id":
		return true
	}
	return strings.HasPrefix(name, "Mcp-")
}

func (g *Gateway) serveURL(w http.ResponseWriter, r *http.Request, t Target) {
	server := t.URL
	if server.AuthConfigID != "" {
		http.Error(w, "MCP instance authenticates through an auth config, which the gateway does not resolve", http.StatusConflict)
		return
	}
	if server.ManagedBy == managedByPlatform {
		http.Error(w, "MCP instance is a platform-managed connection, which the gateway does not proxy", http.StatusConflict)
		return
	}
	endpoint, err := url.Parse(server.EndpointURL)
	if err != nil || (endpoint.Scheme != "http" && endpoint.Scheme != "https") || endpoint.Host == "" {
		http.Error(w, "MCP instance has no http(s) endpoint_url", http.StatusBadGateway)
		return
	}
	headers, err := g.o.Runtime.URLHeaders(r.Context(), t)
	if err != nil {
		g.o.Log.Error("MCP instance credentials could not be resolved", "instance_id", t.InstanceID, "error", err)
		http.Error(w, "MCP instance credentials could not be resolved", http.StatusBadGateway)
		return
	}
	proxy := &httputil.ReverseProxy{
		Transport:     g.o.URLs,
		FlushInterval: -1,
		Rewrite: func(out *httputil.ProxyRequest) {
			out.SetURL(endpoint)
			out.Out.URL.Path = endpoint.Path
			out.Out.URL.RawPath = endpoint.RawPath
			out.Out.URL.RawQuery = endpoint.RawQuery
			fwd := http.Header{}
			for name, values := range out.In.Header {
				if forwardedURLHeader(name) {
					fwd[name] = values
				}
			}
			for name, value := range headers {
				fwd.Set(name, value)
			}
			out.Out.Header = fwd
		},
		ModifyResponse: func(resp *http.Response) error {
			resp.Header.Del(StartingHeader)
			resp.Header.Del(StartFailureHeader)
			resp.Header.Del("Set-Cookie")
			return nil
		},
		ErrorHandler: func(rw http.ResponseWriter, _ *http.Request, perr error) {
			g.o.Log.Warn("MCP URL upstream request failed", "instance_id", t.InstanceID, "error", perr)
			var blocked *netguard.BlockedError
			if errors.As(perr, &blocked) {
				http.Error(rw, perr.Error(), http.StatusForbidden)
				return
			}
			http.Error(rw, "MCP upstream request failed", http.StatusBadGateway)
		},
	}
	proxy.ServeHTTP(w, r)
}
