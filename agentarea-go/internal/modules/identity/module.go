// Package identity is the identity module: workspaces, invitations, memberships and API keys.
package identity

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// Config is identity's settings.
type Config struct {
	// KratosAdminURL is where identities are resolved (AuthSettings.KRATOS_ADMIN_URL).
	KratosAdminURL string
}

// LoadConfig reads identity's settings.
func LoadConfig(l *config.Loader) Config {
	return Config{KratosAdminURL: l.StringEnv("AGENTAREA_AUTH_KRATOS_ADMIN_URL", "http://kratos:4434")}
}

// NewDirectory is the Kratos identity directory for cfg.
func NewDirectory(cfg Config, log *slog.Logger) (service.Directory, error) {
	return store.NewKratos(cfg.KratosAdminURL, nil, log)
}

// NewLinkCodes issues messenger link codes through kv (the Redis broker).
func NewLinkCodes(kv store.KV) service.LinkCodes { return store.LinkCodes{KV: kv} }

// Deps are what identity needs from other modules and the kernel, as interfaces
// declared in its service/deps.go; app passes them in (rule 2).
type Deps struct {
	DB db.Database
	// Graph must also read (authz.Graph) when set.
	Graph  authz.Writer
	Agents agentsapi.Lookup
	// OnWorkspaceCreated is governance's provisioning hook; nil until ported.
	OnWorkspaceCreated service.WorkspaceCreated
	// Directory is nil when no identity provider is configured.
	Directory service.Directory
	// Logos is the artifacts bucket; nil leaves the logo routes unmounted.
	Logos service.Logos
	// LinkCodes is nil without the Redis broker.
	LinkCodes service.LinkCodes
	// Audit is governance's trail; nil records nothing.
	Audit governanceapi.AuditWriter
	// Resources is nil until agents and connections provide the explorer's
	// reads; the explorer routes other than sync are then unmounted.
	Resources service.Resources
	// Workspace, Principal and Admin are the edge's admission (see handlers.Edge).
	Workspace func(http.Handler) http.Handler
	Principal func(http.Handler) http.Handler
	Admin     func(ctx context.Context) error
	Log       *slog.Logger
	Now       func() time.Time
}

// Module is identity, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d         Deps
	svc       *service.Service
	readerErr error
}

// ErrGraphCannotRead is a Graph that writes but cannot read tuples or check.
var ErrGraphCannotRead = errors.New("identity: the authorization graph must also read and check")

// New constructs the module.
func New(d Deps) *Module {
	var reader service.GraphReader
	var readerErr error
	if d.Graph != nil {
		r, ok := d.Graph.(service.GraphReader)
		if !ok {
			readerErr = ErrGraphCannotRead
		}
		reader = r
	}
	return &Module{d: d, readerErr: readerErr, svc: service.New(service.Deps{
		DB: d.DB, Store: store.Store{}, Graph: d.Graph, Reader: reader, Agents: d.Agents,
		OnWorkspaceCreated: d.OnWorkspaceCreated, Directory: d.Directory, Logos: d.Logos,
		LinkCodes: d.LinkCodes, Audit: d.Audit, Resources: d.Resources, Now: d.Now,
	}, d.Log)}
}

// Name is the module's name in the role table.
func (*Module) Name() string { return "identity" }

// Owned lists the workspaces a user owns, which confers administration.
func (m *Module) Owned() authz.OwnedWorkspaces { return m.svc }

// Members is what the members and workspaces toolsets call.
func (m *Module) Members() api.Members { return service.Toolsets{S: m.svc} }

// RunnerKeys issues and revokes the keys of clients' runners (agents' client routes).
func (m *Module) RunnerKeys() api.RunnerKeys { return service.RunnerKeys{S: m.svc} }

// MembershipRemovalHandler finishes a removal in the graph from the outbox
// (workspace.membership.ended).
func (m *Module) MembershipRemovalHandler() (string, events.OutboxHandler) {
	return service.MembershipEndedEvent, m.svc.MembershipRemovalHandler()
}

// Serve is the module's HTTP surface.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			if m.readerErr != nil {
				return m.readerErr
			}
			edge := handlers.Edge{Workspace: m.d.Workspace, Principal: m.d.Principal, Admin: m.d.Admin}
			handlers.Mount(rt.Mux.Chi(), rt.Errors, edge, m.svc)
			handlers.MountRest(rt.Mux.Chi(), rt.Errors, edge, m.svc, handlers.Features{
				Logos: m.d.Logos != nil, Explorer: m.d.Resources != nil,
			})
			return nil
		},
	}
}
