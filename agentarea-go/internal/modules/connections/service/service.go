// Package service holds connections' use cases: the auth configs, OAuth links,
// OpenAPI connections and the lookups other modules read.
package service

import (
	"context"
	"log/slog"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	walletapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
)

// Deps are the service's ports.
type Deps struct {
	DB          db.Database
	Auth        AuthStore
	Links       LinkStore
	Connections ConnectionStore
	// OpenAPIWrites is the openapi_connections writes and full reads (store.OpenAPI).
	OpenAPIWrites OpenAPIWriteStore
	Instances     InstanceStore
	Secrets       Secrets
	Catalog       Catalog
	Graph         Graph
	// Specs is catalog's mcp_servers; Runtime the in-process MCP runtime;
	// Agents agents' tools scan; Policies governance's tool policy reads;
	// Out the outbound HTTP; KV the OAuth state store. A nil port leaves
	// the routes that need it unmounted.
	Specs    Specs
	Runtime  Runtime
	Agents   AgentTools
	Policies ToolPolicies
	// Approvals is agents' approval rule targets (governance).
	Approvals AgentApprovals
	Out       Outbound
	KV        KV
	// OAuthStore is the OAuth connect flow's writes; CatalogItems catalog's
	// one-click API items (nil: catalog-item sign-ins answer 503).
	OAuthStore   OAuthStore
	CatalogItems CatalogItems
	// ClientBundles is agents' read of a client's attachments (/mcp/clients);
	// Audit governance's audit trail of the client endpoint's tool calls
	// (nil: calls run unaudited, logged).
	ClientBundles ClientBundles
	Audit         AuditWriter
	// Wallets pays the 402s of runs' calls from the agent's wallet; nil pays none.
	Wallets walletapi.Wallets
	// HeldCalls is runs' approval gate of calls the policy holds; nil refuses them.
	HeldCalls runsapi.HeldCalls
	// ClientCalls prices, caps and meters calls outside a run; nil runs them unmetered.
	ClientCalls runsapi.ClientToolCalls
	Config      Config
	// Admin refuses a caller in ctx who is not an admin of its workspace.
	Admin func(ctx context.Context) error
	// APIURL and AppURL are the public bases of the API and the webapp.
	APIURL string
	AppURL string
	Log    *slog.Logger
	// Counter counts connector checks and OAuth connects for usage analytics; nil counts nothing.
	Counter analytics.Counter
	// Now is the clock; nil is time.Now.
	Now func() time.Time
	// NewID mints row ids; nil is uuid.New.
	NewID func() uuid.UUID
}

// Service is the connections use cases.
type Service struct {
	d     Deps
	perms authz.Permissions
}

// New builds the service.
func New(d Deps) *Service {
	if d.Log == nil {
		d.Log = slog.New(slog.DiscardHandler)
	}
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.NewID == nil {
		d.NewID = uuid.New
	}
	s := &Service{d: d}
	if d.Graph != nil {
		s.perms = authz.NewPermissions(d.Graph, d.Log)
	}
	return s
}

// Require is route_authz.requires(permission, resource): the caller must hold
// the permission on the resource in the graph.
func (s *Service) Require(ctx context.Context, c authn.Caller, permission, resourceType, id string) error {
	return s.perms.Require(ctx, c, permission, resourceType, id)
}

func (s *Service) read(ctx context.Context, c authn.Caller, fn func(db.Session) error) error {
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}
