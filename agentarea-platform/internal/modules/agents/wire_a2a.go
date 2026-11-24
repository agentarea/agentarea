package agents

import (
	"context"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

// A2ADeps are the ports only the A2A surface need.
type A2ADeps struct {
	// A2AAPIURL is AGENTAREA_API_URL, the host the cards and documents point at.
	A2AAPIURL string
	// A2APrincipal is the optional-auth resolver: authn.Gate.Optional(ctx, token, authn.SurfaceAPI, false).
	// Nil leaves the authenticated A2A routes answering 501.
	A2APrincipal func(ctx context.Context, token string) (*authn.Principal, error)
	// A2ARateLimiter holds the 300 a minute A2A RPC buckets; nil leaves them unlimited.
	A2ARateLimiter httpx.RateLimiter
	// A2AOutbound is the SSRF-guarded transport for member URLs (netguard Member);
	// nil leaves POST /a2a/agent-cards answering 501.
	A2AOutbound http.RoundTripper
	// A2ARuns runs the A2A task methods (runs module); nil answers them unavailable.
	A2ARuns api.A2ARuns
	// A2APushSecrets keeps push-config tokens; A2APushURL guards the webhook URL.
	A2APushSecrets service.A2APushSecrets
	A2APushURL     func(ctx context.Context, rawURL string) error
}

func (m *Module) a2a() *service.A2A {
	return service.NewA2A(m.svc, service.A2APorts{
		APIURL: m.d.A2AAPIURL, AgentURL: m.d.Config.A2AAgentURL, Principal: m.d.A2APrincipal,
		RateLimiter: m.d.A2ARateLimiter, Outbound: m.d.A2AOutbound, Runs: m.d.A2ARuns, PushSecrets: m.d.A2APushSecrets, PushURL: m.d.A2APushURL, Log: m.d.Log,
	})
}

// UseA2A sets the ports of the A2A task methods, which runs provides after
// agents is built; call it before serving.
func (m *Module) UseA2A(runs api.A2ARuns, secrets service.A2APushSecrets, pushURL func(ctx context.Context, rawURL string) error) {
	m.d.A2ARuns, m.d.A2APushSecrets, m.d.A2APushURL = runs, secrets, pushURL
}
