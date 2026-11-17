package connections

import (
	"context"
	"net/http"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

type testOut struct{}

func (testOut) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (testOut) Guard() *netguard.Guard                           { return nil }

// The anonymous client registration is served only behind a rate limiter.
func TestServeRefusesRegistrationWithoutRateLimiter(t *testing.T) {
	m := New(Deps{
		Workspace: func(h http.Handler) http.Handler { return h },
		Admin:     func(context.Context) error { return nil },
		Out:       testOut{},
	})
	err := m.Serve().Mount(serve.Routes{})
	if err == nil || !strings.Contains(err.Error(), "rate limiter") {
		t.Fatalf("mounted without a rate limiter: %v", err)
	}
}
