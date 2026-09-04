package dataplane

import (
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/gin-gonic/gin"
)

// proxied issues a real request through a real server: the reverse proxy needs a
// ResponseWriter a recorder does not provide.
func proxied(t *testing.T, router *gin.Engine, path string) (int, string) {
	t.Helper()

	server := httptest.NewServer(router)
	defer server.Close()

	request, err := http.NewRequest(http.MethodPost, server.URL+path, strings.NewReader(`{"jsonrpc":"2.0"}`))
	if err != nil {
		t.Fatalf("building the request: %v", err)
	}
	request.Header.Set("Authorization", "Bearer "+testToken)
	request.Header.Set("Content-Type", "application/json")

	response, err := (&http.Client{Timeout: 30 * time.Second}).Do(request)
	if err != nil {
		t.Fatalf("proxied request: %v", err)
	}
	defer response.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the response: %v", err)
	}

	return response.StatusCode, strings.TrimSpace(string(body))
}

// reservedAddress hands back an address nothing is listening on yet, which is
// the state a container is in between "created" and "bound".
func reservedAddress(t *testing.T) string {
	t.Helper()

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserving an address: %v", err)
	}
	address := listener.Addr().String()
	if err := listener.Close(); err != nil {
		t.Fatalf("releasing the reserved address: %v", err)
	}

	return address
}

// A create returns as soon as the container is running and has an address, which
// is before the server inside it has bound. The first request lands in that
// window, and answering it with a connection failure reports a workload as
// broken seconds before it starts serving -- which is exactly what verification
// saw when an MCP instance was created and immediately called.
func TestFirstRequestWaitsForAServerThatIsStillBinding(t *testing.T) {
	address := reservedAddress(t)
	backend := &fakeBackend{instances: map[string]*backends.InstanceStatus{
		"mine": {
			ID:          "mine",
			Status:      "running",
			InternalURL: "http://" + address,
			Labels:      map[string]string{OwnerLabel: "agent-1"},
		},
	}}

	served := make(chan struct{})
	go func() {
		time.Sleep(400 * time.Millisecond)
		listener, err := net.Listen("tcp", address)
		if err != nil {
			return
		}
		server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			_, _ = w.Write([]byte("served"))
		})}
		defer server.Close()
		close(served)
		_ = server.Serve(listener)
	}()

	status, body := proxied(t, newTestServer(backend), "/dataplane/v1/instances/mine/proxy/mcp")

	select {
	case <-served:
	default:
		t.Fatal("the request was answered before the server was listening")
	}
	if status != http.StatusOK {
		t.Fatalf("proxy answered %d (%q), want the request held until the server accepted it", status, body)
	}
	if body != "served" {
		t.Fatalf("proxy returned %q, want the upstream response", body)
	}
}

// The wait must not become an unconditional pause: a warm instance answers on
// the first dial and the proxy passes the response straight through.
func TestWarmInstanceIsProxiedImmediately(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("warm"))
	}))
	defer upstream.Close()

	backend := &fakeBackend{instances: map[string]*backends.InstanceStatus{
		"mine": {
			ID:          "mine",
			Status:      "running",
			InternalURL: upstream.URL,
			Labels:      map[string]string{OwnerLabel: "agent-1"},
		},
	}}

	start := time.Now()
	status, body := proxied(t, newTestServer(backend), "/dataplane/v1/instances/mine/proxy/mcp")
	if status != http.StatusOK || body != "warm" {
		t.Fatalf("proxy answered %d (%q), want the upstream response", status, body)
	}
	if elapsed := time.Since(start); elapsed > 2*time.Second {
		t.Fatalf("a warm proxied call took %s, want no startup wait", elapsed)
	}
}
