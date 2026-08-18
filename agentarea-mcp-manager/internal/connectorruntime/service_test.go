package connectorruntime

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
)

type backendStub struct {
	backends.Backend
	mu            sync.Mutex
	instances     map[string]*backends.InstanceStatus
	creates       int
	deleted       []string
	createErr     error
	createThenErr bool
}

func (b *backendStub) GetInstanceStatus(_ context.Context, id string) (*backends.InstanceStatus, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	status, ok := b.instances[id]
	if !ok {
		return nil, backends.ErrInstanceNotFound
	}
	copy := *status
	return &copy, nil
}

func (b *backendStub) CreateInstance(_ context.Context, spec *backends.InstanceSpec) (*backends.InstanceResult, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.creates++
	if b.createErr != nil {
		if b.createThenErr {
			b.instances[spec.InstanceID] = &backends.InstanceStatus{ID: spec.InstanceID, Name: spec.Name, Labels: cloneLabels(spec.Labels), Status: "running", InternalURL: "http://mcp.internal"}
		}
		return nil, b.createErr
	}
	b.instances[spec.InstanceID] = &backends.InstanceStatus{ID: spec.InstanceID, Name: spec.Name, Labels: cloneLabels(spec.Labels), Status: "running", InternalURL: "http://mcp.internal"}
	return &backends.InstanceResult{ID: spec.InstanceID, Name: spec.Name, Status: "running"}, nil
}

func (b *backendStub) DeleteInstance(_ context.Context, id string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.deleted = append(b.deleted, id)
	delete(b.instances, id)
	return nil
}

func (b *backendStub) ListInstances(_ context.Context) ([]*backends.InstanceStatus, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := make([]*backends.InstanceStatus, 0, len(b.instances))
	for _, status := range b.instances {
		copy := *status
		out = append(out, &copy)
	}
	return out, nil
}

func (b *backendStub) PerformHealthCheck(_ context.Context, id string) (*backends.HealthCheckResult, error) {
	if _, err := b.GetInstanceStatus(context.Background(), id); err != nil {
		return nil, err
	}
	return &backends.HealthCheckResult{Healthy: true}, nil
}

func newService(t *testing.T, backend *backendStub, doer HTTPDoer) *Service {
	t.Helper()
	service, err := New(backend, Config{DataPlaneID: "dp-1", HTTPClient: doer, MaxRequestBodyBytes: 32, MaxResponseBodyBytes: 32, MaxResponseChunkBytes: 8, MaxHeaderFields: 10})
	if err != nil {
		t.Fatal(err)
	}
	return service
}

func owned(id string) *backends.InstanceStatus {
	return &backends.InstanceStatus{ID: id, Status: "running", InternalURL: "http://mcp.internal", Labels: map[string]string{DataPlaneIDLabel: "dp-1"}}
}

func TestCreateStampsOwnershipAndReusesDuplicate(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{}}
	service := newService(t, backend, nil)
	spec := &backends.InstanceSpec{InstanceID: "one", Name: "one", Labels: map[string]string{DataPlaneIDLabel: "caller", "keep": "value"}}

	first, err := service.Create(context.Background(), spec)
	if err != nil {
		t.Fatal(err)
	}
	second, err := service.Create(context.Background(), spec)
	if err != nil {
		t.Fatal(err)
	}
	if backend.creates != 1 {
		t.Fatalf("creates = %d, want one", backend.creates)
	}
	if first.Operation.ID != second.Operation.ID || !second.Operation.Reused {
		t.Fatalf("operations = %#v then %#v; want stable duplicate operation", first.Operation, second.Operation)
	}
	if spec.Labels[DataPlaneIDLabel] != "caller" {
		t.Fatalf("caller spec was mutated: %#v", spec.Labels)
	}
	if got := backend.instances["one"].Labels; got[DataPlaneIDLabel] != "dp-1" || got["keep"] != "value" {
		t.Fatalf("stamped labels = %#v", got)
	}
}

func TestCreateReconcilesAnAmbiguousBackendFailureOnce(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{}, createErr: errors.New("response lost"), createThenErr: true}
	service := newService(t, backend, nil)

	result, err := service.Create(context.Background(), &backends.InstanceSpec{InstanceID: "one", Name: "one"})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Operation.Reused || backend.creates != 1 {
		t.Fatalf("result = %#v, creates = %d; want one reconciled create", result, backend.creates)
	}
}

func TestOperationsRefuseUnownedInstances(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"theirs": {ID: "theirs", Status: "running", InternalURL: "http://mcp.internal", Labels: map[string]string{DataPlaneIDLabel: "dp-other"}}}}
	service := newService(t, backend, roundTripper(func(*http.Request) (*http.Response, error) { t.Fatal("unowned request was proxied"); return nil, nil }))

	for name, operation := range map[string]func() error{
		"create": func() error {
			_, err := service.Create(context.Background(), &backends.InstanceSpec{InstanceID: "theirs", Name: "theirs"})
			return err
		},
		"get":    func() error { _, err := service.Get(context.Background(), "theirs"); return err },
		"delete": func() error { _, err := service.Delete(context.Background(), "theirs"); return err },
		"health": func() error { _, err := service.Health(context.Background(), "theirs"); return err },
		"proxy": func() error {
			_, err := service.ExecuteHTTP(context.Background(), HTTPRequest{InstanceID: "theirs", Method: http.MethodPost, Path: "/mcp"})
			return err
		},
	} {
		t.Run(name, func(t *testing.T) {
			if err := operation(); !errors.Is(err, ErrUnowned) {
				t.Fatalf("error = %v, want ErrUnowned", err)
			}
		})
	}
	if len(backend.deleted) != 0 {
		t.Fatalf("deleted unowned instance: %v", backend.deleted)
	}
}

func TestExecuteHTTPStripsControlHeadersAndPreservesMCPResponse(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"mine": owned("mine")}}
	doer := roundTripper(func(request *http.Request) (*http.Response, error) {
		for _, header := range []string{"Authorization", "Cookie", "Connection", "X-Remove"} {
			if request.Header.Get(header) != "" {
				t.Errorf("forwarded %s header: %q", header, request.Header.Get(header))
			}
		}
		if got := request.Header.Get("Content-Type"); got != "application/json" {
			t.Errorf("content type = %q", got)
		}
		payload, _ := io.ReadAll(request.Body)
		if string(payload) != `{"jsonrpc":"2.0"}` {
			t.Errorf("body = %q", payload)
		}
		return &http.Response{StatusCode: http.StatusAccepted, Header: http.Header{"Content-Type": {"application/json"}, "Mcp-Session-Id": {"s-1"}, "Connection": {"X-Internal"}, "X-Internal": {"no"}}, Body: io.NopCloser(strings.NewReader("response-body"))}, nil
	})
	service := newService(t, backend, doer)
	response, err := service.ExecuteHTTP(context.Background(), HTTPRequest{InstanceID: "mine", Method: http.MethodPost, Path: "/mcp", Header: http.Header{"Authorization": {"Bearer control"}, "Cookie": {"session=control"}, "Connection": {"X-Remove"}, "X-Remove": {"remove"}, "Content-Type": {"application/json"}}, Body: strings.NewReader(`{"jsonrpc":"2.0"}`)})
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusAccepted || string(response.Body) != "response-body" {
		t.Fatalf("response = %#v", response)
	}
	if response.Header.Get("Content-Type") != "application/json" || response.Header.Get("Mcp-Session-Id") != "s-1" {
		t.Fatalf("MCP content headers lost: %#v", response.Header)
	}
	if response.Header.Get("X-Internal") != "" {
		t.Fatalf("connection-token header leaked: %#v", response.Header)
	}
	for _, chunk := range response.Chunks {
		if len(chunk) > 8 {
			t.Fatalf("chunk is too large: %d", len(chunk))
		}
	}
}

func TestExecuteHTTPPreservesProviderProxyPathPrefix(t *testing.T) {
	status := owned("mine")
	status.InternalURL = "http://data-plane.internal/dataplane/v1/instances/mine/proxy"
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"mine": status}}
	service := newService(t, backend, roundTripper(func(request *http.Request) (*http.Response, error) {
		if request.URL.Path != "/dataplane/v1/instances/mine/proxy/mcp" {
			t.Fatalf("proxy path = %q", request.URL.Path)
		}
		return &http.Response{StatusCode: http.StatusOK, Header: make(http.Header), Body: io.NopCloser(strings.NewReader("ok"))}, nil
	}))
	if _, err := service.ExecuteHTTP(context.Background(), HTTPRequest{InstanceID: "mine", Method: http.MethodPost, Path: "/mcp"}); err != nil {
		t.Fatal(err)
	}
}

func TestExecuteHTTPCancellationPropagates(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"mine": owned("mine")}}
	service := newService(t, backend, roundTripper(func(request *http.Request) (*http.Response, error) {
		<-request.Context().Done()
		return nil, request.Context().Err()
	}))
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := service.ExecuteHTTP(ctx, HTTPRequest{InstanceID: "mine", Method: http.MethodGet, Path: "/mcp", Body: bytes.NewReader(nil)})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want context.Canceled", err)
	}
}

func TestExecuteHTTPRejectsOversizedResponse(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"mine": owned("mine")}}
	service := newService(t, backend, roundTripper(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Header: http.Header{"Content-Type": {"application/json"}}, Body: io.NopCloser(strings.NewReader(strings.Repeat("x", 33)))}, nil
	}))
	_, err := service.ExecuteHTTP(context.Background(), HTTPRequest{InstanceID: "mine", Method: http.MethodGet, Path: "/mcp"})
	if !errors.Is(err, ErrResponseTooLarge) {
		t.Fatalf("error = %v, want ErrResponseTooLarge", err)
	}
}

func TestExecuteHTTPRejectsTooManyResponseHeaders(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"mine": owned("mine")}}
	service := newService(t, backend, roundTripper(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Header: http.Header{"Content-Type": {"application/json"}, "Mcp-Session-Id": {"one"}}, Body: io.NopCloser(strings.NewReader("ok"))}, nil
	}))
	service.cfg.MaxHeaderFields = 1
	_, err := service.ExecuteHTTP(context.Background(), HTTPRequest{InstanceID: "mine", Method: http.MethodGet, Path: "/mcp"})
	if !errors.Is(err, ErrTooManyHeaders) {
		t.Fatalf("error = %v, want ErrTooManyHeaders", err)
	}
}

func TestExecuteHTTPStreamEmitsFirstChunkBeforeEOF(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"mine": owned("mine")}}
	reader, writer := io.Pipe()
	service := newService(t, backend, roundTripper(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Header: http.Header{"Content-Type": {"text/event-stream"}}, Body: reader}, nil
	}))
	sink := &streamSink{firstChunk: make(chan struct{})}
	done := make(chan error, 1)
	go func() {
		done <- service.ExecuteHTTPStream(context.Background(), HTTPRequest{InstanceID: "mine", Method: http.MethodGet, Path: "/mcp"}, sink)
	}()

	go func() { _, _ = io.WriteString(writer, "event: ready\n\n") }()
	select {
	case <-sink.firstChunk:
	case <-time.After(time.Second):
		t.Fatal("first MCP stream chunk was not emitted")
	}
	select {
	case err := <-done:
		t.Fatalf("stream completed before EOF: %v", err)
	default:
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if sink.headerCount() != 1 {
		t.Fatalf("headers emitted %d times, want one", sink.headerCount())
	}
}

func TestExecuteHTTPStreamAppliesSinkBackpressure(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"mine": owned("mine")}}
	body := &trackingReadCloser{reader: strings.NewReader("abcdefghijklmnop"), closed: make(chan struct{})}
	service := newService(t, backend, roundTripper(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Header: make(http.Header), Body: body}, nil
	}))
	release := make(chan struct{})
	sink := &streamSink{firstChunk: make(chan struct{}), blockChunk: release}
	done := make(chan error, 1)
	go func() {
		done <- service.ExecuteHTTPStream(context.Background(), HTTPRequest{InstanceID: "mine", Method: http.MethodGet, Path: "/mcp"}, sink)
	}()

	select {
	case <-sink.firstChunk:
	case <-time.After(time.Second):
		t.Fatal("sink did not receive first chunk")
	}
	if reads := body.readCount(); reads != 1 {
		t.Fatalf("upstream reads while sink blocked = %d, want one", reads)
	}
	close(release)
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestExecuteHTTPStreamCancellationClosesEndlessBody(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"mine": owned("mine")}}
	body := newBlockingReadCloser()
	service := newService(t, backend, roundTripper(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Header: make(http.Header), Body: body}, nil
	}))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		done <- service.ExecuteHTTPStream(ctx, HTTPRequest{InstanceID: "mine", Method: http.MethodGet, Path: "/mcp"}, &streamSink{})
	}()

	select {
	case <-body.started:
	case <-time.After(time.Second):
		t.Fatal("stream did not begin reading the endless body")
	}
	cancel()
	select {
	case <-body.closed:
	case <-time.After(time.Second):
		t.Fatal("cancellation did not promptly close upstream body")
	}
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("error = %v, want context.Canceled", err)
		}
	case <-time.After(time.Second):
		t.Fatal("stream goroutine did not exit after cancellation")
	}
}

func TestExecuteHTTPStreamSinkErrorStopsReading(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"mine": owned("mine")}}
	body := &trackingReadCloser{reader: strings.NewReader("abcdefghijklmnop"), closed: make(chan struct{})}
	service := newService(t, backend, roundTripper(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Header: make(http.Header), Body: body}, nil
	}))
	want := errors.New("downstream disconnected")
	err := service.ExecuteHTTPStream(context.Background(), HTTPRequest{InstanceID: "mine", Method: http.MethodGet, Path: "/mcp"}, &streamSink{chunkErr: want})
	if !errors.Is(err, want) {
		t.Fatalf("error = %v, want sink error", err)
	}
	if reads := body.readCount(); reads != 1 {
		t.Fatalf("upstream reads after sink failure = %d, want one", reads)
	}
	select {
	case <-body.closed:
	default:
		t.Fatal("body was not closed after sink failure")
	}
}

func TestExecuteHTTPStreamHasNoDefaultTotalLimit(t *testing.T) {
	backend := &backendStub{instances: map[string]*backends.InstanceStatus{"mine": owned("mine")}}
	service := newService(t, backend, roundTripper(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(strings.Repeat("x", 40)))}, nil
	}))
	sink := &streamSink{}
	if err := service.ExecuteHTTPStream(context.Background(), HTTPRequest{InstanceID: "mine", Method: http.MethodGet, Path: "/mcp"}, sink); err != nil {
		t.Fatalf("unbounded stream failed: %v", err)
	}
	service.cfg.MaxStreamBodyBytes = 33
	if err := service.ExecuteHTTPStream(context.Background(), HTTPRequest{InstanceID: "mine", Method: http.MethodGet, Path: "/mcp"}, &streamSink{}); !errors.Is(err, ErrStreamTooLarge) {
		t.Fatalf("limited stream error = %v, want ErrStreamTooLarge", err)
	}
}

type streamSink struct {
	mu         sync.Mutex
	headers    int
	firstChunk chan struct{}
	chunkOnce  sync.Once
	blockChunk <-chan struct{}
	chunkErr   error
}

func (s *streamSink) WriteHeaders(context.Context, HTTPResponseHeaders) error {
	s.mu.Lock()
	s.headers++
	s.mu.Unlock()
	return nil
}

func (s *streamSink) WriteChunk(_ context.Context, _ []byte) error {
	s.chunkOnce.Do(func() {
		if s.firstChunk != nil {
			close(s.firstChunk)
		}
	})
	if s.blockChunk != nil {
		<-s.blockChunk
	}
	return s.chunkErr
}

func (s *streamSink) headerCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.headers
}

type trackingReadCloser struct {
	mu     sync.Mutex
	reader io.Reader
	reads  int
	closed chan struct{}
	once   sync.Once
}

func (r *trackingReadCloser) Read(p []byte) (int, error) {
	r.mu.Lock()
	r.reads++
	r.mu.Unlock()
	return r.reader.Read(p)
}

func (r *trackingReadCloser) Close() error {
	r.once.Do(func() {
		if r.closed != nil {
			close(r.closed)
		}
	})
	return nil
}

func (r *trackingReadCloser) readCount() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.reads
}

type blockingReadCloser struct {
	started   chan struct{}
	closed    chan struct{}
	readOnce  sync.Once
	closeOnce sync.Once
}

func newBlockingReadCloser() *blockingReadCloser {
	return &blockingReadCloser{started: make(chan struct{}), closed: make(chan struct{})}
}

func (r *blockingReadCloser) Read([]byte) (int, error) {
	r.readOnce.Do(func() { close(r.started) })
	<-r.closed
	return 0, io.ErrClosedPipe
}

func (r *blockingReadCloser) Close() error {
	r.closeOnce.Do(func() { close(r.closed) })
	return nil
}

type roundTripper func(*http.Request) (*http.Response, error)

func (f roundTripper) Do(request *http.Request) (*http.Response, error) { return f(request) }

func cloneLabels(labels map[string]string) map[string]string {
	copy := make(map[string]string, len(labels))
	for key, value := range labels {
		copy[key] = value
	}
	return copy
}
