// Package wallet is the wallet module: agent wallets and payment records.
package wallet

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// Deps are what wallet needs from other modules and the kernel, as interfaces
// declared in its service/deps.go; app passes them in (rule 2).
type Deps struct {
	DB db.Database
	// Agents resolves the agent a path names; a slug resolves only when the
	// lookup also implements service.SlugResolver.
	Agents agentsapi.Lookup
	// Secrets is the workspace secret store the wallet keys live in.
	Secrets service.Secrets
	// Workspace admits the caller into /v1/workspaces/{workspace} and puts
	// it in the request context (authn.CallerFrom).
	Workspace func(http.Handler) http.Handler
	// Admin refuses a caller who does not administer the workspace.
	Admin func(ctx context.Context) error
	Log   *slog.Logger
	Now   func() time.Time
}

// Module is wallet, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d   Deps
	svc *service.Service
}

// New constructs the module.
func New(d Deps) *Module {
	return &Module{d: d, svc: service.New(service.Deps{
		DB: d.DB, Store: store.Store{}, Agents: service.AgentsFrom(d.Agents), Secrets: d.Secrets, Log: d.Log, Now: d.Now,
	})}
}

// Wallets is what runs and insights call about wallets and payments.
func (m *Module) Wallets() api.Wallets { return m.svc }

// AgentCredentials is what agents calls as it deletes an agent.
func (m *Module) AgentCredentials() api.AgentCredentials { return m.svc }

// Name is the module's name in the role table.
func (*Module) Name() string { return "wallet" }

// Serve is the module's HTTP surface.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			handlers.Mount(rt.Mux.Chi(), rt.Errors, m.d.Workspace, handlers.New(m.svc, m.d.Admin))
			return nil
		},
	}
}
