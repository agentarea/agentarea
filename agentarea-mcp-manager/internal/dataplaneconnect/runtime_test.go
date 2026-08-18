package dataplaneconnect

import (
	"context"
	"errors"
	"net/http"
	"testing"
	"time"
)

type staticCapabilities struct{ mcp, sandbox bool }

func (s staticCapabilities) Capabilities() (bool, bool) { return s.mcp, s.sandbox }

type blockingStream struct{ started chan struct{} }

func (s blockingStream) Run(ctx context.Context) error {
	close(s.started)
	<-ctx.Done()
	return nil
}

func TestCapabilitiesComeFromInitializedSource(t *testing.T) {
	cfg := testConfig(t, "https://control.test")
	cfg.Capabilities = Capabilities{MCP: true, Sandbox: true}
	cfg.MCPProvider = "kubernetes"
	cfg.SandboxProvider = "kubernetes"
	cfg.KubernetesNamespace = "execution"
	cfg.SandboxTaskLeaseTTL = time.Minute
	c, err := NewClient(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if got := c.capabilities(); got.MCP || got.Sandbox {
		t.Fatalf("configured capability leaked into report: %#v", got)
	}
	c.SetCapabilitySource(staticCapabilities{mcp: true})
	if got := c.capabilities(); !got.MCP || got.Sandbox {
		t.Fatalf("capabilities = %#v", got)
	}
}

func TestRunCancelsOutboundStreamOnShutdown(t *testing.T) {
	cfg := testConfig(t, "https://control.test")
	cfg.HeartbeatInterval = time.Hour
	c, err := NewClient(cfg)
	if err != nil {
		t.Fatal(err)
	}
	// Run's initial heartbeat needs a persisted identity but no live HTTP call
	// because this test exercises the stream loop directly.
	started := make(chan struct{})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	c.SetConnectorStream(blockingStream{started: started})
	go func() { <-started; cancel() }()
	if err := c.runWithStream(ctx, c.stream()); err != nil {
		t.Fatal(err)
	}
}

func TestConnectorShutdownWaitIsBounded(t *testing.T) {
	result := make(chan error)
	started := time.Now()
	waitForConnectorStop(result, 10*time.Millisecond)
	if elapsed := time.Since(started); elapsed > time.Second {
		t.Fatalf("bounded wait took %s", elapsed)
	}
}

func TestHeartbeatRejectionClassification(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden, http.StatusNotFound, http.StatusUnprocessableEntity} {
		if !heartbeatRejected(&ControlPlaneStatusError{StatusCode: status}) {
			t.Fatalf("status %d must stop the agent", status)
		}
	}
	for _, err := range []error{
		&ControlPlaneStatusError{StatusCode: http.StatusTooManyRequests},
		&ControlPlaneStatusError{StatusCode: http.StatusBadGateway},
		errors.New("temporary EOF"),
	} {
		if heartbeatRejected(err) {
			t.Fatalf("transient error %v must not stop the agent", err)
		}
	}
}
