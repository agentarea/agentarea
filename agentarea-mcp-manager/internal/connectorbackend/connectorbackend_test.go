package connectorbackend

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/connectorhub"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

type operationHubStub struct {
	request connectorhub.OperationRequest
	result  *connectorhub.OperationResult
	err     error
}

func (s *operationHubStub) StartOperation(_ context.Context, _ string, request connectorhub.OperationRequest) (*connectorhub.OperationResult, error) {
	s.request = request
	return s.result, s.err
}

func TestBackendMapsConcreteOperationsAndPayloads(t *testing.T) {
	result, _ := json.Marshal(backends.InstanceResult{ID: "mcp-1", Status: "running"})
	hub := &operationHubStub{result: &connectorhub.OperationResult{Status: connectorhub.ResultSucceeded, Payload: result}}
	backend, err := NewBackend(hub, "dp-eu")
	if err != nil {
		t.Fatal(err)
	}
	created, err := backend.CreateInstance(context.Background(), &backends.InstanceSpec{InstanceID: "mcp-1", Name: "catalog"})
	if err != nil || created.ID != "mcp-1" {
		t.Fatalf("CreateInstance() = %#v, %v", created, err)
	}
	if hub.request.Kind != connectorproto.OperationKind_OPERATION_KIND_MCP_CREATE.String() || hub.request.ContentType != "application/json" {
		t.Fatalf("operation = %#v", hub.request)
	}
	var spec backends.InstanceSpec
	if err := json.Unmarshal(hub.request.Payload, &spec); err != nil || spec.InstanceID != "mcp-1" {
		t.Fatalf("create payload = %s (%v)", hub.request.Payload, err)
	}

	list, _ := json.Marshal([]*backends.InstanceStatus{{ID: "mcp-1"}})
	hub.result.Payload = list
	instances, err := backend.ListInstances(context.Background())
	if err != nil || len(instances) != 1 || hub.request.Kind != connectorproto.OperationKind_OPERATION_KIND_MCP_LIST.String() {
		t.Fatalf("ListInstances() = %#v, %v; operation=%s", instances, err, hub.request.Kind)
	}
}

func TestBackendUsesEveryLifecycleOperationKind(t *testing.T) {
	hub := &operationHubStub{result: &connectorhub.OperationResult{Status: connectorhub.ResultSucceeded}}
	backend, _ := NewBackend(hub, "dp-eu")
	tests := []struct {
		name string
		kind connectorproto.OperationKind
		call func() error
	}{
		{
			name: "delete", kind: connectorproto.OperationKind_OPERATION_KIND_MCP_DELETE,
			call: func() error { return backend.DeleteInstance(context.Background(), "mcp-1") },
		},
		{
			name: "get", kind: connectorproto.OperationKind_OPERATION_KIND_MCP_GET,
			call: func() error {
				hub.result.Payload = []byte(`{"id":"mcp-1"}`)
				_, err := backend.GetInstanceStatus(context.Background(), "mcp-1")
				return err
			},
		},
		{
			name: "health", kind: connectorproto.OperationKind_OPERATION_KIND_MCP_HEALTH,
			call: func() error {
				hub.result.Payload = []byte(`{"healthy":true}`)
				_, err := backend.PerformHealthCheck(context.Background(), "mcp-1")
				return err
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if err := test.call(); err != nil {
				t.Fatal(err)
			}
			if hub.request.Kind != test.kind.String() {
				t.Fatalf("kind = %q, want %q", hub.request.Kind, test.kind.String())
			}
			if test.name != "delete" {
				return
			}
			var body struct {
				InstanceID string `json:"instance_id"`
			}
			if err := json.Unmarshal(hub.request.Payload, &body); err != nil || body.InstanceID != "mcp-1" {
				t.Fatalf("delete payload = %q (%v)", hub.request.Payload, err)
			}
		})
	}
}

func TestBackendMapsNotFoundAndBadPayload(t *testing.T) {
	hub := &operationHubStub{result: &connectorhub.OperationResult{Status: connectorhub.ResultFailed, Error: "not_found"}}
	backend, _ := NewBackend(hub, "dp-eu")
	if _, err := backend.GetInstanceStatus(context.Background(), "missing"); !errors.Is(err, backends.ErrInstanceNotFound) {
		t.Fatalf("GetInstanceStatus() error = %v, want ErrInstanceNotFound", err)
	}
	hub.result = &connectorhub.OperationResult{Status: connectorhub.ResultSucceeded, Payload: []byte("not-json")}
	if _, err := backend.PerformHealthCheck(context.Background(), "mcp-1"); err == nil {
		t.Fatal("PerformHealthCheck accepted a malformed connector payload")
	}
}

func TestBackendLifecycleErrorsComeFromHub(t *testing.T) {
	hub := connectorhub.New(connectorhub.Config{})
	backend, _ := NewBackend(hub, "dp-eu")
	if _, err := backend.ListInstances(context.Background()); !errors.Is(err, connectorhub.ErrConnectorUnavailable) {
		t.Fatalf("offline error = %v", err)
	}

	sender := &sessionSender{}
	session, err := hub.Register(connectorhub.Registration{DataPlaneID: "dp-eu", ConnectorInstanceID: "connector-1", Capabilities: []connectorhub.Capability{connectorhub.CapabilityOperations}, Sender: sender})
	if err != nil {
		t.Fatal(err)
	}
	sender.setSession(session)
	if err := session.SetDraining(true); err != nil {
		t.Fatal(err)
	}
	if _, err := backend.ListInstances(context.Background()); !errors.Is(err, connectorhub.ErrConnectorDraining) {
		t.Fatalf("draining error = %v", err)
	}
	if err := session.SetDraining(false); err != nil {
		t.Fatal(err)
	}
	if err := session.SetCapabilities(nil, 1); err != nil {
		t.Fatal(err)
	}
	if _, err := backend.ListInstances(context.Background()); !errors.Is(err, connectorhub.ErrCapabilityUnavailable) {
		t.Fatalf("capability error = %v", err)
	}
}

type probeStub struct{ err error }

func (p probeStub) ProbeConnector(context.Context, string, connectorhub.Capability) error {
	return p.err
}

func TestBackendInitializeUsesOptionalProbe(t *testing.T) {
	backend, _ := NewBackend(&operationHubStub{}, "dp-eu", probeStub{err: connectorhub.ErrConnectorUnavailable})
	if err := backend.Initialize(context.Background()); !errors.Is(err, connectorhub.ErrConnectorUnavailable) {
		t.Fatalf("Initialize() error = %v", err)
	}
}

type sessionSender struct {
	mu       sync.Mutex
	session  *connectorhub.Session
	commands []connectorhub.Command
	onSend   func(*connectorhub.Session, connectorhub.Command)
}

func (s *sessionSender) setSession(session *connectorhub.Session) {
	s.mu.Lock()
	s.session = session
	s.mu.Unlock()
}

func (s *sessionSender) Send(_ context.Context, command connectorhub.Command) error {
	s.mu.Lock()
	s.commands = append(s.commands, command)
	session, onSend := s.session, s.onSend
	s.mu.Unlock()
	if onSend != nil {
		onSend(session, command)
	}
	return nil
}

func (s *sessionSender) commandKinds() []connectorhub.CommandKind {
	s.mu.Lock()
	defer s.mu.Unlock()
	kinds := make([]connectorhub.CommandKind, 0, len(s.commands))
	for _, command := range s.commands {
		kinds = append(kinds, command.Kind)
	}
	return kinds
}

func TestRoundTripperStreamsFirstResponseBeforeRequestEOF(t *testing.T) {
	hub := connectorhub.New(connectorhub.Config{})
	sender := &sessionSender{}
	session, err := hub.Register(connectorhub.Registration{DataPlaneID: "dp-eu", ConnectorInstanceID: "connector-1", Capabilities: []connectorhub.Capability{connectorhub.CapabilityProxy}, Sender: sender})
	if err != nil {
		t.Fatal(err)
	}
	sender.setSession(session)
	sender.onSend = func(session *connectorhub.Session, command connectorhub.Command) {
		if command.Kind == connectorhub.CommandProxyStart {
			if err := session.ProxyHeaders(command.Proxy.ID, connectorhub.ProxyResponseHeaders{StatusCode: http.StatusOK, Headers: []connectorhub.Header{{Name: "Content-Type", Value: "text/plain"}, {Name: "Connection", Value: "X-Remove"}, {Name: "X-Remove", Value: "no"}}}); err != nil {
				panic(err)
			}
			if err := session.ProxyChunk(command.Proxy.ID, 0, []byte("first")); err != nil {
				panic(err)
			}
		}
		if command.Kind == connectorhub.CommandProxyEnd && command.ProxyEnd.Reason == "complete" {
			_ = session.ProxyEnd(command.ProxyEnd.ID, "complete")
		}
	}
	transport, err := NewRoundTripper(hub, "dp-eu", 2)
	if err != nil {
		t.Fatal(err)
	}
	body := newGateBody([]byte("later"))
	request, _ := http.NewRequest(http.MethodPost, "http://unused/mcp?x=1", body)
	response, err := transport.RoundTrip(request)
	if err != nil {
		t.Fatal(err)
	}
	if response.Header.Get("X-Remove") != "" {
		t.Fatalf("hop-by-hop response header was retained: %#v", response.Header)
	}
	chunk := make([]byte, 5)
	if _, err := io.ReadFull(response.Body, chunk); err != nil || string(chunk) != "first" {
		t.Fatalf("first response chunk = %q, %v", chunk, err)
	}
	body.release()
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestRoundTripperCancellationClosesConnectorProxy(t *testing.T) {
	hub := connectorhub.New(connectorhub.Config{})
	sender := &sessionSender{}
	session, _ := hub.Register(connectorhub.Registration{DataPlaneID: "dp-eu", ConnectorInstanceID: "connector-1", Capabilities: []connectorhub.Capability{connectorhub.CapabilityProxy}, Sender: sender})
	sender.setSession(session)
	sender.onSend = func(session *connectorhub.Session, command connectorhub.Command) {
		if command.Kind == connectorhub.CommandProxyStart {
			_ = session.ProxyHeaders(command.Proxy.ID, connectorhub.ProxyResponseHeaders{StatusCode: http.StatusOK})
		}
	}
	transport, _ := NewRoundTripper(hub, "dp-eu")
	ctx, cancel := context.WithCancel(context.Background())
	request, _ := http.NewRequestWithContext(ctx, http.MethodGet, "http://unused/mcp", nil)
	response, err := transport.RoundTrip(request)
	if err != nil {
		t.Fatal(err)
	}
	cancel()
	_, err = response.Body.Read(make([]byte, 1))
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelled body read = %v", err)
	}
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		for _, kind := range sender.commandKinds() {
			if kind == connectorhub.CommandProxyEnd {
				return
			}
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("connector did not receive proxy cancellation")
}

func TestSandboxExecutorPreservesExecutionIDAndRejectsBadResponse(t *testing.T) {
	response, _ := json.Marshal(warmpool.ExecuteResponse{ExitCode: 7, Stdout: "done"})
	hub := &operationHubStub{result: &connectorhub.OperationResult{Status: connectorhub.ResultSucceeded, Payload: response}}
	executor, err := NewSandboxExecutor(hub, "dp-eu")
	if err != nil {
		t.Fatal(err)
	}
	got, err := executor.Execute(context.Background(), "exec-42", warmpool.ExecuteRequest{CommandBody: "echo done"})
	if err != nil || got.ExitCode != 7 || hub.request.ID != "exec-42" || hub.request.Kind != connectorproto.OperationKind_OPERATION_KIND_SANDBOX_EXECUTE.String() {
		t.Fatalf("Execute() = %#v, %v; operation=%#v", got, err, hub.request)
	}
	var envelope struct {
		ExecutionID string `json:"execution_id"`
	}
	_ = json.Unmarshal(hub.request.Payload, &envelope)
	if envelope.ExecutionID != "exec-42" {
		t.Fatalf("execution ID = %q", envelope.ExecutionID)
	}
	hub.result.Payload = []byte("bad-json")
	if _, err := executor.Execute(context.Background(), "exec-43", warmpool.ExecuteRequest{}); err == nil {
		t.Fatal("Execute accepted malformed sandbox payload")
	}
}

type gateBody struct {
	data     []byte
	releaseC chan struct{}
	once     sync.Once
}

func newGateBody(data []byte) *gateBody { return &gateBody{data: data, releaseC: make(chan struct{})} }

func (b *gateBody) Read(dst []byte) (int, error) {
	<-b.releaseC
	if len(b.data) == 0 {
		return 0, io.EOF
	}
	n := copy(dst, b.data)
	b.data = b.data[n:]
	return n, nil
}
func (b *gateBody) Close() error { b.release(); return nil }
func (b *gateBody) release()     { b.once.Do(func() { close(b.releaseC) }) }

var _ io.ReadCloser = (*gateBody)(nil)
