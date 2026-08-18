package connectortransport

import (
	"context"
	"crypto/tls"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/agentarea/mcp-manager/internal/connectorauth"
	"github.com/agentarea/mcp-manager/internal/connectorhub"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
	"github.com/agentarea/mcp-manager/internal/connectorproto/connectorprotoconnect"
	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"
)

const transportSecret = "test-bearer-credential"

type testAuthenticator struct {
	mu    sync.Mutex
	calls int
	last  connectorauth.IncomingConnector
}

func (a *testAuthenticator) Authenticate(_ context.Context, incoming connectorauth.IncomingConnector) (connectorauth.AuthenticatedLogicalPlane, error) {
	if incoming.NodeCredential != transportSecret {
		return connectorauth.AuthenticatedLogicalPlane{}, connectorauth.ErrAuthenticationFailed
	}
	a.mu.Lock()
	a.calls++
	a.last = incoming
	a.mu.Unlock()
	return connectorauth.AuthenticatedLogicalPlane{DataPlaneID: incoming.Hello.DataPlaneID, ConnectorInstanceID: incoming.Hello.ConnectorInstanceID}, nil
}

func (a *testAuthenticator) Calls() int { a.mu.Lock(); defer a.mu.Unlock(); return a.calls }
func (a *testAuthenticator) Last() connectorauth.IncomingConnector {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.last
}

type testDispatcher struct {
	cancelled chan struct{}
}

func (d *testDispatcher) DispatchOperation(ctx context.Context, start *connectorproto.OperationStart) (*connectorproto.OperationResult, error) {
	if string(start.GetRequestPayload()) == `"wait-cancel"` {
		<-ctx.Done()
		select {
		case d.cancelled <- struct{}{}:
		default:
		}
		return nil, ctx.Err()
	}
	return &connectorproto.OperationResult{Status: connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_SUCCEEDED, ResponsePayload: append([]byte(nil), start.GetRequestPayload()...), ContentType: start.GetContentType()}, nil
}

func (d *testDispatcher) StartProxy(_ context.Context, _ *connectorproto.ProxyStart) (ProxyExchange, error) {
	return &testProxy{responses: make(chan ProxyResponse, 4)}, nil
}

type testProxy struct {
	mu        sync.Mutex
	responses chan ProxyResponse
	closed    bool
}

func (p *testProxy) WriteProxyRequest(_ context.Context, _ *connectorproto.ProxyRequestChunk) error {
	return nil
}
func (p *testProxy) Responses() <-chan ProxyResponse { return p.responses }
func (p *testProxy) Close() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if !p.closed {
		p.closed = true
		close(p.responses)
	}
	return nil
}
func (p *testProxy) EndProxyRequest(_ context.Context, end *connectorproto.ProxyRequestEnd) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.closed {
		return errors.New("closed")
	}
	p.responses <- ProxyResponse{Headers: &connectorproto.ProxyResponseHeaders{StatusCode: http.StatusOK, Headers: []*connectorproto.Header{{Name: "Content-Type", Value: "text/plain"}}}}
	p.responses <- ProxyResponse{Chunk: &connectorproto.ProxyResponseChunk{Sequence: 0, Data: []byte("incremental")}}
	p.responses <- ProxyResponse{End: &connectorproto.ProxyEnd{Reason: end.GetReason()}}
	p.closed = true
	close(p.responses)
	return nil
}

func newTLSServer(t *testing.T, auth connectorauth.Authenticator, hub *connectorhub.Hub) *httptest.Server {
	t.Helper()
	server, err := NewServer(ServerConfig{Authenticator: auth, Hub: hub, HeartbeatInterval: time.Second})
	if err != nil {
		t.Fatal(err)
	}
	path, handler := server.Handler()
	mux := http.NewServeMux()
	mux.Handle(path, handler)
	httpServer := httptest.NewUnstartedServer(mux)
	httpServer.EnableHTTP2 = true
	httpServer.StartTLS()
	t.Cleanup(httpServer.Close)
	return httpServer
}

func newH2CServer(t *testing.T, auth connectorauth.Authenticator, hub *connectorhub.Hub) *httptest.Server {
	return newH2CServerWithHeartbeat(t, auth, hub, time.Second)
}

func newH2CServerWithHeartbeat(t *testing.T, auth connectorauth.Authenticator, hub *connectorhub.Hub, heartbeat time.Duration) *httptest.Server {
	t.Helper()
	server, err := NewServer(ServerConfig{Authenticator: auth, Hub: hub, HeartbeatInterval: heartbeat})
	if err != nil {
		t.Fatal(err)
	}
	path, handler := server.Handler()
	mux := http.NewServeMux()
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(h2c.NewHandler(mux, &http2.Server{}))
	t.Cleanup(httpServer.Close)
	return httpServer
}

func TestHeartbeatKeepsConnectorSessionActive(t *testing.T) {
	hub := connectorhub.New(connectorhub.Config{})
	auth := &testAuthenticator{}
	server := newH2CServerWithHeartbeat(t, auth, hub, 20*time.Millisecond)
	client, err := NewClient(ClientConfig{
		ControlPlaneURL: server.URL, DataPlaneID: "dp-heartbeat", ConnectorInstanceID: "connector-heartbeat",
		NodeCredential: transportSecret, ConnectorVersion: "test", AllowInsecureDevelopment: true,
		Capabilities:     []connectorproto.Capability{connectorproto.Capability_CAPABILITY_OPERATIONS},
		ReconnectInitial: 10 * time.Millisecond, ReconnectMax: 50 * time.Millisecond,
	}, &testDispatcher{})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- client.Run(ctx) }()
	defer func() {
		cancel()
		select {
		case <-done:
		case <-time.After(time.Second):
			t.Fatal("heartbeat client did not stop")
		}
	}()
	await(t, func() bool { return auth.Calls() > 0 })
	connections := auth.Calls()
	time.Sleep(100 * time.Millisecond)
	if auth.Calls() != connections {
		t.Fatalf("heartbeat caused reconnect: connections %d -> %d", connections, auth.Calls())
	}
	result, err := hub.StartOperation(context.Background(), "dp-heartbeat", connectorhub.OperationRequest{ID: "after-heartbeats", Kind: "OPERATION_KIND_MCP_GET", Payload: []byte(`"alive"`), ContentType: "application/json"})
	if err != nil || string(result.Payload) != `"alive"` {
		t.Fatalf("operation after heartbeats = %#v, %v", result, err)
	}
}

func newTestClient(t *testing.T, endpoint string, dispatcher Dispatcher) *Client {
	t.Helper()
	httpClient := &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, ForceAttemptHTTP2: true}}
	client, err := NewClient(ClientConfig{ControlPlaneURL: endpoint, DataPlaneID: "dp-a", ConnectorInstanceID: "connector-a", NodeCredential: transportSecret, ConnectorVersion: "test", Capabilities: []connectorproto.Capability{connectorproto.Capability_CAPABILITY_OPERATIONS, connectorproto.Capability_CAPABILITY_PROXY, connectorproto.Capability_CAPABILITY_MCP}, MaxConcurrentOps: 4, HTTPClient: httpClient, ReconnectInitial: 10 * time.Millisecond, ReconnectMax: 50 * time.Millisecond}, dispatcher)
	if err != nil {
		t.Fatal(err)
	}
	return client
}

func TestPlainVMConnectsWithoutProviderCapabilities(t *testing.T) {
	hub := connectorhub.New(connectorhub.Config{})
	auth := &testAuthenticator{}
	server := newH2CServer(t, auth, hub)
	client, err := NewClient(ClientConfig{
		ControlPlaneURL: server.URL, DataPlaneID: "dp-empty", ConnectorInstanceID: "connector-empty",
		NodeCredential: transportSecret, ConnectorVersion: "test", AllowInsecureDevelopment: true,
		ReconnectInitial: 10 * time.Millisecond, ReconnectMax: 50 * time.Millisecond,
	}, &testDispatcher{})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- client.Run(ctx) }()
	defer func() {
		cancel()
		select {
		case <-done:
		case <-time.After(time.Second):
			t.Fatal("plain VM connector did not stop")
		}
	}()
	await(t, func() bool { return auth.Calls() > 0 })
	last := auth.Last()
	if last.Hello.Capabilities["mcp"] || last.Hello.Capabilities["sandbox"] {
		t.Fatalf("plain VM advertised workload capabilities: %#v", last.Hello.Capabilities)
	}
	_, err = hub.StartOperation(context.Background(), "dp-empty", connectorhub.OperationRequest{Kind: connectorproto.OperationKind_OPERATION_KIND_MCP_LIST.String(), Payload: []byte(`{}`), ContentType: "application/json"})
	if !errors.Is(err, connectorhub.ErrCapabilityUnavailable) {
		t.Fatalf("operation on providerless VM error = %v", err)
	}
}

func TestClientDevelopmentHTTPIsLoopbackOnly(t *testing.T) {
	base := ClientConfig{
		DataPlaneID: "dp-a", ConnectorInstanceID: "connector-a",
		NodeCredential: transportSecret, ConnectorVersion: "test",
		AllowInsecureDevelopment: true,
	}
	base.ControlPlaneURL = "http://127.0.0.1:17999"
	if _, err := NewClient(base, &testDispatcher{}); err != nil {
		t.Fatalf("loopback development URL rejected: %v", err)
	}
	base.ControlPlaneURL = "http://connector.example"
	if _, err := NewClient(base, &testDispatcher{}); err == nil || !strings.Contains(err.Error(), "limited to loopback") {
		t.Fatalf("remote clear-text URL accepted: %v", err)
	}
}

func await(t *testing.T, condition func() bool) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if condition() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("condition was not met")
}

func TestConnectTLSH2LifecycleProxyCancellationAndReconnect(t *testing.T) {
	hub := connectorhub.New(connectorhub.Config{})
	auth := &testAuthenticator{}
	server := newTLSServer(t, auth, hub)
	dispatcher := &testDispatcher{cancelled: make(chan struct{}, 1)}
	client := newTestClient(t, server.URL, dispatcher)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- client.Run(ctx) }()
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(time.Second):
			t.Fatal("client did not stop")
		}
	})

	// Authentication proves the stream is registered. Retrying one operation ID
	// as a readiness probe is invalid: a timed-out attempt is deliberately kept
	// for reconciliation and the next attempt must then be rejected as a
	// duplicate.
	await(t, func() bool { return auth.Calls() > 0 })
	readyCtx, readyCancel := context.WithTimeout(context.Background(), time.Second)
	_, err := hub.StartOperation(readyCtx, "dp-a", connectorhub.OperationRequest{ID: "ready", Kind: "OPERATION_KIND_MCP_GET", Payload: []byte(`"ready"`), ContentType: "application/json"})
	readyCancel()
	if err != nil {
		t.Fatalf("connector readiness operation failed: %v", err)
	}
	result, err := hub.StartOperation(context.Background(), "dp-a", connectorhub.OperationRequest{ID: "lifecycle", Kind: "OPERATION_KIND_MCP_GET", Payload: []byte(`"request"`), ContentType: "application/json"})
	if err != nil || string(result.Payload) != `"request"` {
		t.Fatalf("operation result = %#v, %v", result, err)
	}

	proxy, err := hub.OpenProxy(context.Background(), "dp-a", connectorhub.ProxyRequest{ID: "streaming-post", Method: http.MethodPost, Path: "/mcp"})
	if err != nil {
		t.Fatal(err)
	}
	if err := proxy.Write(context.Background(), []byte("post-body")); err != nil {
		t.Fatal(err)
	}
	if err := proxy.CloseRequest(context.Background()); err != nil {
		t.Fatal(err)
	}
	headers, err := proxy.Headers(context.Background())
	if err != nil || headers.StatusCode != http.StatusOK {
		t.Fatalf("proxy headers = %#v, %v", headers, err)
	}
	chunk, err := proxy.Read(context.Background())
	if err != nil || string(chunk) != "incremental" {
		t.Fatalf("proxy chunk = %q, %v", chunk, err)
	}
	if _, err := proxy.Read(context.Background()); !errors.Is(err, io.EOF) {
		t.Fatalf("proxy terminal error = %v, want EOF", err)
	}
	connectionsAfterProxy := auth.Calls()
	proxy.Close()
	time.Sleep(20 * time.Millisecond)
	if auth.Calls() != connectionsAfterProxy {
		t.Fatal("closing an already completed proxy disconnected the connector")
	}
	afterProxy, err := hub.StartOperation(context.Background(), "dp-a", connectorhub.OperationRequest{ID: "after-proxy", Kind: "OPERATION_KIND_MCP_GET", Payload: []byte(`"still-connected"`), ContentType: "application/json"})
	if err != nil || string(afterProxy.Payload) != `"still-connected"` {
		t.Fatalf("operation after completed proxy = %#v, %v", afterProxy, err)
	}

	cancelCtx, cancelOperation := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancelOperation()
	cancelResult, err := hub.StartOperation(cancelCtx, "dp-a", connectorhub.OperationRequest{ID: "cancel", Kind: "OPERATION_KIND_MCP_GET", Payload: []byte(`"wait-cancel"`), ContentType: "application/json"})
	// The caller deadline and the connector's terminal deadline result race by
	// design; either is a valid observation of the same cancellation.
	if !errors.Is(err, context.DeadlineExceeded) && (err != nil || cancelResult == nil || cancelResult.Status != connectorhub.ResultDeadlineExceeded) {
		t.Fatalf("cancelled operation result = %#v, error = %v", cancelResult, err)
	}
	select {
	case <-dispatcher.cancelled:
	case <-time.After(time.Second):
		t.Fatal("dispatcher did not receive cancellation")
	}

	// Heartbeat and drain failures cancel the child session rather than the Run
	// context. That cancellation must tear down the current stream and reconnect;
	// otherwise later operations are accepted into an already-cancelled context.
	callsBeforeSessionCancel := auth.Calls()
	client.mu.Lock()
	activeSession := client.session
	client.mu.Unlock()
	if activeSession == nil {
		t.Fatal("connector client has no active session")
	}
	activeSession.cancel(errors.New("test session cancellation"))
	await(t, func() bool { return auth.Calls() > callsBeforeSessionCancel })
	recovered, err := hub.StartOperation(context.Background(), "dp-a", connectorhub.OperationRequest{ID: "after-session-cancel", Kind: "OPERATION_KIND_MCP_GET", Payload: []byte(`"recovered"`), ContentType: "application/json"})
	if err != nil || string(recovered.Payload) != `"recovered"` {
		t.Fatalf("operation after session cancellation = %#v, %v", recovered, err)
	}

	initialCalls := auth.Calls()
	server.CloseClientConnections()
	await(t, func() bool { return auth.Calls() > initialCalls })
}

func TestInvalidFrameAndAuthenticationDoNotExposeCredential(t *testing.T) {
	hub := connectorhub.New(connectorhub.Config{})
	server := newTLSServer(t, &testAuthenticator{}, hub)
	httpClient := &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, ForceAttemptHTTP2: true}}
	service := connectorprotoconnect.NewOutboundConnectorClient(httpClient, server.URL)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	stream := service.Connect(ctx)
	stream.RequestHeader().Set("Authorization", "Bearer "+transportSecret)
	if err := stream.Send(&connectorproto.ConnectorToControl{ProtocolVersion: connectorproto.ProtocolVersionV1, DataPlaneId: &connectorproto.DataPlaneID{Value: "dp-a"}, ConnectorInstanceId: &connectorproto.ConnectorInstanceID{Value: "connector-a"}, Message: &connectorproto.ConnectorToControl_Heartbeat{Heartbeat: &connectorproto.Heartbeat{SentAtUnixMillis: 1}}}); err != nil {
		t.Fatal(err)
	}
	_, err := stream.Receive()
	if err == nil {
		t.Fatal("invalid first frame was accepted")
	}
	if strings.Contains(err.Error(), transportSecret) {
		t.Fatalf("credential leaked into error: %v", err)
	}
	var connectErr *connect.Error
	if !errors.As(err, &connectErr) || connectErr.Code() != connect.CodeInvalidArgument {
		t.Fatalf("error = %v, want invalid argument", err)
	}
}
