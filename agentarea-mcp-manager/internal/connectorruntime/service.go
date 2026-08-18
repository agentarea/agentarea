// Package connectorruntime contains the provider-neutral runtime operations an
// agent connector needs. It deliberately has no listener or provider setup:
// transports authenticate and decode requests before calling Service, while
// Docker and Kubernetes can be supplied through backends.Backend.
package connectorruntime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
)

const (
	// DataPlaneIDLabel identifies the data plane allowed to operate an instance.
	// It matches the label already used by the legacy data-plane HTTP surface so
	// a migration does not silently orphan workloads.
	DataPlaneIDLabel = "agentarea.io/dataplane-id"

	defaultStartupTimeout        = 3 * time.Minute
	defaultPollInterval          = 250 * time.Millisecond
	defaultMaxHeaderFields       = 100
	defaultMaxBodyBytes          = int64(4 << 20)
	defaultMaxResponseChunkBytes = 64 << 10
)

var (
	ErrUnowned             = errors.New("instance is not owned by this data plane")
	ErrNotFound            = errors.New("instance not found")
	ErrRequestTooLarge     = errors.New("MCP request body exceeds configured limit")
	ErrResponseTooLarge    = errors.New("MCP response body exceeds configured limit")
	ErrStreamTooLarge      = errors.New("MCP stream exceeds configured limit")
	ErrTooManyHeaders      = errors.New("HTTP header count exceeds configured limit")
	ErrInvalidProxyRequest = errors.New("invalid MCP proxy request")
	ErrInvalidStreamSink   = errors.New("invalid MCP stream sink")
)

// HTTPDoer is intentionally smaller than http.Client. It makes the executor
// testable and permits a transport-specific client to be injected by a future
// connector without coupling this package to a provider.
type HTTPDoer interface {
	Do(*http.Request) (*http.Response, error)
}

// Config defines logical ownership and the resource bounds for one runtime.
type Config struct {
	DataPlaneID string

	StartupTimeout time.Duration
	PollInterval   time.Duration

	MaxHeaderFields       int
	MaxRequestBodyBytes   int64
	MaxResponseBodyBytes  int64
	MaxResponseChunkBytes int
	// MaxStreamBodyBytes is an optional total limit for one streaming
	// response. Zero leaves streams unbounded while MaxResponseChunkBytes is
	// always enforced.
	MaxStreamBodyBytes int64

	HTTPClient HTTPDoer
}

// Service coordinates one logical data plane's instances through a backend.
type Service struct {
	backend backends.Backend
	cfg     Config
	http    HTTPDoer

	// Backend implementations are not universally idempotent. Serialising the
	// short check/create/reconcile section prevents duplicate creates in one
	// connector process; the preflight check preserves the property after a
	// connector restart.
	createMu sync.Mutex
}

// New creates a service. Backend and HTTP client are injected so this package
// has no Docker, Kubernetes, listener, or sandbox-provider dependency.
func New(backend backends.Backend, cfg Config) (*Service, error) {
	if backend == nil {
		return nil, errors.New("connector runtime backend is required")
	}
	if strings.TrimSpace(cfg.DataPlaneID) == "" {
		return nil, errors.New("connector runtime data_plane_id is required")
	}
	if cfg.StartupTimeout <= 0 {
		cfg.StartupTimeout = defaultStartupTimeout
	}
	if cfg.PollInterval <= 0 {
		cfg.PollInterval = defaultPollInterval
	}
	if cfg.MaxHeaderFields <= 0 {
		cfg.MaxHeaderFields = defaultMaxHeaderFields
	}
	if cfg.MaxRequestBodyBytes <= 0 {
		cfg.MaxRequestBodyBytes = defaultMaxBodyBytes
	}
	if cfg.MaxResponseBodyBytes <= 0 {
		cfg.MaxResponseBodyBytes = defaultMaxBodyBytes
	}
	if cfg.MaxResponseChunkBytes <= 0 {
		cfg.MaxResponseChunkBytes = defaultMaxResponseChunkBytes
	}
	if cfg.HTTPClient == nil {
		// Transparent gzip decoding would change both Content-Encoding and the
		// body observed by the connector. MCP response framing is part of the
		// protocol contract, so the default transport keeps it byte-for-byte.
		transport := http.DefaultTransport.(*http.Transport).Clone()
		transport.DisableCompression = true
		cfg.HTTPClient = &http.Client{Transport: transport}
	}

	return &Service{backend: backend, cfg: cfg, http: cfg.HTTPClient}, nil
}

// Operation is a deterministic description of a lifecycle action. Its ID is
// stable across retries, which lets a connector correlate duplicate messages
// without maintaining an unbounded operation journal.
type Operation struct {
	ID         string
	Action     string
	InstanceID string
	Reused     bool
}

// CreateResult reports whether a backend create was needed or an owned
// instance was reconciled and reused.
type CreateResult struct {
	Operation Operation
	Instance  *backends.InstanceResult
}

// Create stamps the service's data_plane_id and performs at most one create.
// A duplicate first queries the backend and reuses an owned instance. If a
// backend reports a create error after accepting the request, exactly one
// reconciliation lookup is made before returning the original failure.
func (s *Service) Create(ctx context.Context, spec *backends.InstanceSpec) (*CreateResult, error) {
	if spec == nil || strings.TrimSpace(spec.InstanceID) == "" {
		return nil, fmt.Errorf("create: instance_id is required")
	}

	s.createMu.Lock()
	defer s.createMu.Unlock()

	op := s.operation("create", spec.InstanceID)
	if existing, err := s.backend.GetInstanceStatus(ctx, spec.InstanceID); err == nil {
		if !s.owns(existing) {
			return nil, ErrUnowned
		}
		op.Reused = true
		return &CreateResult{Operation: op, Instance: resultFromStatus(existing)}, nil
	} else if !errors.Is(err, backends.ErrInstanceNotFound) {
		return nil, fmt.Errorf("inspect existing instance %q: %w", spec.InstanceID, err)
	}

	stamped := cloneSpec(spec)
	stamped.Labels[DataPlaneIDLabel] = s.cfg.DataPlaneID
	result, createErr := s.backend.CreateInstance(ctx, stamped)
	if createErr == nil {
		return &CreateResult{Operation: op, Instance: result}, nil
	}

	// A timeout or lost backend response is ambiguous. Reconcile once, but do
	// not retry creation: retries can create a second provider workload.
	if existing, reconcileErr := s.backend.GetInstanceStatus(ctx, spec.InstanceID); reconcileErr == nil {
		if !s.owns(existing) {
			return nil, ErrUnowned
		}
		op.Reused = true
		return &CreateResult{Operation: op, Instance: resultFromStatus(existing)}, nil
	}
	return nil, fmt.Errorf("create instance %q: %w", spec.InstanceID, createErr)
}

// Delete removes an owned instance. A missing instance is a successful,
// idempotent retirement; an unowned one is always refused.
func (s *Service) Delete(ctx context.Context, instanceID string) (*Operation, error) {
	op := s.operation("delete", instanceID)
	_, err := s.requireOwned(ctx, instanceID)
	if errors.Is(err, ErrNotFound) {
		op.Reused = true
		return &op, nil
	}
	if err != nil {
		return nil, err
	}
	if err := s.backend.DeleteInstance(ctx, instanceID); err != nil && !errors.Is(err, backends.ErrInstanceNotFound) {
		return nil, fmt.Errorf("delete instance %q: %w", instanceID, err)
	}
	return &op, nil
}

// Get returns an owned instance only.
func (s *Service) Get(ctx context.Context, instanceID string) (*backends.InstanceStatus, error) {
	return s.requireOwned(ctx, instanceID)
}

// List returns only instances stamped with this service's data_plane_id.
func (s *Service) List(ctx context.Context) ([]*backends.InstanceStatus, error) {
	all, err := s.backend.ListInstances(ctx)
	if err != nil {
		return nil, fmt.Errorf("list instances: %w", err)
	}
	owned := make([]*backends.InstanceStatus, 0, len(all))
	for _, status := range all {
		if s.owns(status) {
			owned = append(owned, status)
		}
	}
	return owned, nil
}

// Health runs a backend health check for an owned instance only.
func (s *Service) Health(ctx context.Context, instanceID string) (*backends.HealthCheckResult, error) {
	if _, err := s.requireOwned(ctx, instanceID); err != nil {
		return nil, err
	}
	result, err := s.backend.PerformHealthCheck(ctx, instanceID)
	if err != nil {
		return nil, fmt.Errorf("health check instance %q: %w", instanceID, err)
	}
	return result, nil
}

// HTTPRequest is an origin-form request to an MCP instance. A connector can
// build it from HTTP, ConnectRPC, or a persistent agent stream.
type HTTPRequest struct {
	InstanceID string
	Method     string
	Path       string
	RawQuery   string
	Header     http.Header
	Body       io.Reader
}

// HTTPResponse preserves MCP response status, content headers, and body. Chunks
// are bounded views of Body for transports that frame streaming responses.
type HTTPResponse struct {
	StatusCode int
	Header     http.Header
	Body       []byte
	Chunks     [][]byte
}

// HTTPResponseHeaders is the first frame supplied to an HTTPStreamSink.
// Header is a sanitized copy: it contains MCP content headers but no hop-by-hop
// fields or fields nominated by Connection.
type HTTPResponseHeaders struct {
	StatusCode int
	Header     http.Header
}

// HTTPStreamSink receives one response header frame followed by body chunks.
// Calls are synchronous: a blocked WriteChunk applies backpressure to the
// upstream MCP response instead of buffering an unbounded stream in memory.
// Implementations should observe ctx so they can unblock promptly on cancel.
type HTTPStreamSink interface {
	WriteHeaders(ctx context.Context, headers HTTPResponseHeaders) error
	WriteChunk(ctx context.Context, chunk []byte) error
}

// ExecuteHTTP sends an MCP request to a running, owned instance. Control-plane
// credentials and hop-by-hop headers never cross the workload boundary.
func (s *Service) ExecuteHTTP(ctx context.Context, request HTTPRequest) (*HTTPResponse, error) {
	response, err := s.openHTTP(ctx, request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	read, err := readBounded(ctx, response.Body, s.cfg.MaxResponseBodyBytes, s.cfg.MaxResponseChunkBytes, ErrResponseTooLarge)
	if err != nil {
		return nil, err
	}
	return &HTTPResponse{StatusCode: response.StatusCode, Header: filteredHeaders(response.Header, false), Body: read.Body, Chunks: read.Chunks}, nil
}

// ExecuteHTTPStream sends an MCP request and forwards its response incrementally.
// It emits response headers exactly once before reading the first body chunk.
// Unlike ExecuteHTTP, a stream has no total byte limit unless MaxStreamBodyBytes
// is configured; every emitted chunk remains bounded by MaxResponseChunkBytes.
func (s *Service) ExecuteHTTPStream(ctx context.Context, request HTTPRequest, sink HTTPStreamSink) error {
	if sink == nil {
		return ErrInvalidStreamSink
	}
	response, err := s.openHTTP(ctx, request)
	if err != nil {
		return err
	}
	defer response.Body.Close()

	// A sink can legitimately block for downstream flow control. Closing the
	// upstream body from this small watcher still interrupts a blocked Read when
	// the connector context expires, without allocating a goroutine per chunk.
	stopWatcher := make(chan struct{})
	watcherDone := make(chan struct{})
	go func() {
		defer close(watcherDone)
		select {
		case <-ctx.Done():
			_ = response.Body.Close()
		case <-stopWatcher:
		}
	}()
	defer func() {
		close(stopWatcher)
		<-watcherDone
	}()

	if err := sink.WriteHeaders(ctx, HTTPResponseHeaders{StatusCode: response.StatusCode, Header: filteredHeaders(response.Header, false)}); err != nil {
		return fmt.Errorf("write MCP response headers: %w", err)
	}

	buffer := make([]byte, s.cfg.MaxResponseChunkBytes)
	var streamed int64
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		n, readErr := response.Body.Read(buffer)
		if n < 0 || n > len(buffer) {
			return errors.New("HTTP body reader returned invalid chunk size")
		}
		if n > 0 {
			if int64(n) > int64(^uint64(0)>>1)-streamed {
				return ErrStreamTooLarge
			}
			streamed += int64(n)
			if s.cfg.MaxStreamBodyBytes > 0 && streamed > s.cfg.MaxStreamBodyBytes {
				return ErrStreamTooLarge
			}
			// The reader buffer is reused. Give transports an owned chunk so a
			// sink may hand it to its own async encoder after WriteChunk returns.
			if err := sink.WriteChunk(ctx, append([]byte(nil), buffer[:n]...)); err != nil {
				return fmt.Errorf("write MCP response chunk: %w", err)
			}
		}
		if readErr == io.EOF {
			return nil
		}
		if readErr != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			return fmt.Errorf("read MCP response: %w", readErr)
		}
	}
}

func (s *Service) openHTTP(ctx context.Context, request HTTPRequest) (*http.Response, error) {
	if strings.TrimSpace(request.InstanceID) == "" || strings.TrimSpace(request.Method) == "" || request.Path == "" || !strings.HasPrefix(request.Path, "/") {
		return nil, ErrInvalidProxyRequest
	}
	if err := validateHeaderCount(request.Header, s.cfg.MaxHeaderFields); err != nil {
		return nil, err
	}
	body, err := readBounded(ctx, request.Body, s.cfg.MaxRequestBodyBytes, s.cfg.MaxResponseChunkBytes, ErrRequestTooLarge)
	if err != nil {
		return nil, err
	}

	status, err := s.requireOwned(ctx, request.InstanceID)
	if err != nil {
		return nil, err
	}
	status, err = s.ensureRunning(ctx, request.InstanceID, status)
	if err != nil {
		return nil, err
	}
	target, err := parseTarget(status.InternalURL)
	if err != nil {
		return nil, err
	}
	basePath := strings.TrimRight(target.Path, "/")
	target.Path = basePath + request.Path
	target.RawPath = ""
	target.RawQuery = request.RawQuery

	outbound, err := http.NewRequestWithContext(ctx, request.Method, target.String(), bytes.NewReader(body.Body))
	if err != nil {
		return nil, fmt.Errorf("build MCP request: %w", err)
	}
	outbound.Header = filteredHeaders(request.Header, true)
	response, err := s.http.Do(outbound)
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return nil, fmt.Errorf("execute MCP request: %w", err)
	}
	if response == nil || response.Body == nil {
		return nil, errors.New("execute MCP request: empty HTTP response")
	}
	if err := validateHeaderCount(response.Header, s.cfg.MaxHeaderFields); err != nil {
		_ = response.Body.Close()
		return nil, err
	}
	return response, nil
}

type instanceStarter interface {
	StartInstance(context.Context, string) error
}

func (s *Service) ensureRunning(ctx context.Context, instanceID string, status *backends.InstanceStatus) (*backends.InstanceStatus, error) {
	if status.Status == "running" && status.InternalURL != "" {
		return status, nil
	}
	if status.Status != "running" {
		starter, ok := s.backend.(instanceStarter)
		if !ok {
			return nil, fmt.Errorf("instance %q is %s and backend cannot start it", instanceID, status.Status)
		}
		if err := starter.StartInstance(ctx, instanceID); err != nil {
			return nil, fmt.Errorf("start instance %q: %w", instanceID, err)
		}
	}

	startupCtx, cancel := context.WithTimeout(ctx, s.cfg.StartupTimeout)
	defer cancel()
	for {
		refreshed, err := s.backend.GetInstanceStatus(startupCtx, instanceID)
		if err == nil && s.owns(refreshed) && refreshed.Status == "running" && refreshed.InternalURL != "" {
			return refreshed, nil
		}
		if startupCtx.Err() != nil {
			return nil, startupCtx.Err()
		}
		select {
		case <-startupCtx.Done():
			return nil, startupCtx.Err()
		case <-time.After(s.cfg.PollInterval):
		}
	}
}

func (s *Service) requireOwned(ctx context.Context, instanceID string) (*backends.InstanceStatus, error) {
	if strings.TrimSpace(instanceID) == "" {
		return nil, ErrNotFound
	}
	status, err := s.backend.GetInstanceStatus(ctx, instanceID)
	if errors.Is(err, backends.ErrInstanceNotFound) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get instance %q: %w", instanceID, err)
	}
	if !s.owns(status) {
		return nil, ErrUnowned
	}
	return status, nil
}

func (s *Service) owns(status *backends.InstanceStatus) bool {
	return status != nil && status.Labels != nil && status.Labels[DataPlaneIDLabel] == s.cfg.DataPlaneID
}

func (s *Service) operation(action, instanceID string) Operation {
	hash := sha256.Sum256([]byte(s.cfg.DataPlaneID + "\x00" + action + "\x00" + instanceID))
	return Operation{ID: action + "-" + hex.EncodeToString(hash[:16]), Action: action, InstanceID: instanceID}
}

func cloneSpec(spec *backends.InstanceSpec) *backends.InstanceSpec {
	copy := *spec
	copy.Labels = make(map[string]string, len(spec.Labels)+1)
	for key, value := range spec.Labels {
		copy.Labels[key] = value
	}
	return &copy
}

func resultFromStatus(status *backends.InstanceStatus) *backends.InstanceResult {
	return &backends.InstanceResult{ID: status.ID, Name: status.Name, URL: status.URL, InternalURL: status.InternalURL, Status: status.Status, CreatedAt: status.CreatedAt}
}

func parseTarget(raw string) (*url.URL, error) {
	target, err := url.Parse(raw)
	if err != nil || target.Scheme == "" || target.Host == "" || (target.Scheme != "http" && target.Scheme != "https") {
		return nil, fmt.Errorf("instance reports unusable internal URL %q", raw)
	}
	return target, nil
}

func validateHeaderCount(header http.Header, max int) error {
	count := 0
	for _, values := range header {
		count += len(values)
	}
	if count > max {
		return ErrTooManyHeaders
	}
	return nil
}

var hopByHopHeaders = map[string]struct{}{
	"connection": {}, "keep-alive": {}, "proxy-authenticate": {}, "proxy-authorization": {},
	"te": {}, "trailer": {}, "transfer-encoding": {}, "upgrade": {},
}

func filteredHeaders(input http.Header, request bool) http.Header {
	connectionTokens := make(map[string]struct{})
	for key, values := range input {
		if strings.EqualFold(key, "Connection") {
			for _, value := range values {
				for _, token := range strings.Split(value, ",") {
					connectionTokens[strings.ToLower(strings.TrimSpace(token))] = struct{}{}
				}
			}
		}
	}
	out := make(http.Header, len(input))
	for key, values := range input {
		lower := strings.ToLower(key)
		if _, blocked := hopByHopHeaders[lower]; blocked {
			continue
		}
		if _, blocked := connectionTokens[lower]; blocked {
			continue
		}
		if request && (lower == "authorization" || lower == "cookie" || lower == "cookie2") {
			continue
		}
		out[key] = append([]string(nil), values...)
	}
	return out
}

type boundedRead struct {
	Body   []byte
	Chunks [][]byte
}

func readBounded(ctx context.Context, reader io.Reader, maxBody int64, maxChunk int, limitErr error) (*boundedRead, error) {
	if reader == nil {
		return &boundedRead{}, nil
	}
	buffer := make([]byte, maxChunk)
	result := &boundedRead{Body: make([]byte, 0, minInt64(maxBody, int64(maxChunk)))}
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		// Read only one byte beyond the remaining budget. This detects an
		// oversized stream without allowing a reader to hand this service an
		// arbitrary extra chunk before it is rejected.
		remaining := maxBody - int64(len(result.Body))
		readSize := minInt64(int64(maxChunk), remaining+1)
		n, err := reader.Read(buffer[:readSize])
		if n < 0 || n > len(buffer) {
			return nil, errors.New("HTTP body reader returned invalid chunk size")
		}
		if n > 0 {
			if int64(n) > maxBody-int64(len(result.Body)) {
				return nil, limitErr
			}
			chunk := append([]byte(nil), buffer[:n]...)
			result.Chunks = append(result.Chunks, chunk)
			result.Body = append(result.Body, chunk...)
		}
		if err == io.EOF {
			return result, nil
		}
		if err != nil {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			return nil, err
		}
	}
}

func minInt64(left, right int64) int64 {
	if left < right {
		return left
	}
	return right
}
