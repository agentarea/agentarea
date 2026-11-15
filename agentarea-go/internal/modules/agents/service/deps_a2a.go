package service

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// A2APorts are the ports of the A2A surface.
type A2APorts struct {
	// APIURL is AGENTAREA_API_URL: the API host the cards and documents point at.
	APIURL string
	// AgentURL is AGENTAREA_A2A_AGENT_URL with its {agent_id} placeholder.
	AgentURL string
	// Principal is resolve_principal_from_token on an optional-auth edge
	// (authn.Gate.Optional with admitTurn false): nil for a token it refuses.
	// Nil leaves the authenticated A2A routes answering 501.
	Principal func(ctx context.Context, token string) (*authn.Principal, error)
	// RateLimiter holds the A2A RPC buckets; nil leaves the calls unlimited.
	RateLimiter httpx.RateLimiter
	// Outbound reaches a member-supplied URL through the SSRF guard
	// (netguard Member transport); nil leaves agent-cards answering 501.
	Outbound http.RoundTripper
	// Tasks answers the A2A task methods; Runs, when set, builds it over runs.
	// Without either the task methods answer unavailable.
	Tasks A2ATasks
	Runs  agentsapi.A2ARuns
	// PushSecrets keeps push-config callback tokens; PushURL refuses a
	// webhook URL the outbound policy does not admit.
	PushSecrets A2APushSecrets
	PushURL     func(ctx context.Context, rawURL string) error
	Log         *slog.Logger
}

// A2APushSecrets is the workspace secret store a push config's token goes to,
// acting for the caller.
type A2APushSecrets interface {
	Set(ctx context.Context, c authn.Caller, name, value string) error
	Delete(ctx context.Context, c authn.Caller, name string) error
}

// A2ATasks is AgentAreaRequestHandler's task side: SendMessage, GetTask,
// ListTasks, CancelTask and the push-config methods on the task system.
type A2ATasks interface {
	// Handle answers one call with its MessageToDict result, or a *domain.A2ARPCError.
	Handle(ctx context.Context, call A2ACall) (domain.A2AJSON, error)
	// Stream calls emit with each StreamResponse of SendStreamingMessage and
	// SubscribeToTask; an error before the first emit answers as plain JSON.
	Stream(ctx context.Context, call A2ACall, emit func(domain.A2AJSON) error) error
}

// A2ACall is one A2A task method call for one agent.
type A2ACall struct {
	Method    string
	Params    any
	RequestID any
	AgentID   uuid.UUID
	RPCURL    string
	Auth      domain.A2AAuth
	Caller    authn.Caller
}
