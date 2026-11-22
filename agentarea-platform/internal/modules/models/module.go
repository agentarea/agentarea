// Package models is the models module: provider configurations, model
// instances, discovery and the provider transports a run's model calls go through.
package models

import (
	"context"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

// Deps are what models needs from other modules and the kernel; app passes them in.
type Deps struct {
	DB      db.Database
	Catalog service.Catalog
	Secrets service.Secrets
	Out     service.Outbound
	// Admin refuses a caller who does not administer the workspace.
	Admin func(ctx context.Context) error
	// Pricing is the deployment's customer pricing, read when a request needs it.
	Pricing func() money.CustomerPricing
	// LocalHost is AGENTAREA_LOCAL_HOST.
	LocalHost string
	// APIURL is AGENTAREA_API_URL.
	APIURL string
	// Principal authenticates a route on no workspace; Workspace admits the
	// caller into /v1/workspaces/{workspace}.
	Principal, Workspace func(http.Handler) http.Handler
	Now                  func() time.Time
}

// Module is models, constructed once per process.
type Module struct {
	d   Deps
	svc *service.Service
}

// New constructs the module.
func New(d Deps) *Module {
	return &Module{d: d, svc: service.New(service.Deps{
		DB: d.DB, Store: store.Store{}, VideoJobs: store.VideoJobs{}, Catalog: d.Catalog, Secrets: d.Secrets, Out: d.Out, Admin: d.Admin, Pricing: d.Pricing,
		LocalHost: d.LocalHost, APIURL: d.APIURL, Now: d.Now,
	})}
}

// Caller is the model call a run makes.
func (m *Module) Caller() api.Caller { return m.svc }

// Resolver resolves a run's model instance.
func (m *Module) Resolver() api.Resolver { return m.svc }

// Directory is what a bundle deploy reads of models.
func (m *Module) Directory() api.Directory { return m.svc }

// ModelKinds is what agents reads to validate a model_id.
func (m *Module) ModelKinds() api.ModelKinds { return m.svc }

// SpecUse is what catalog reads of models.
func (m *Module) SpecUse() api.SpecUse { return m.svc }

// Name is the module's name in the role table.
func (*Module) Name() string { return "models" }

// Serve is the module's HTTP surface.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			handlers.Mount(rt.Mux.Chi(), rt.Errors, m.d.Principal, m.d.Workspace, handlers.New(m.svc))
			return nil
		},
	}
}

// SpecUses is which specs configs and instances are on, for catalog sync.
func (m *Module) SpecUses() api.SpecUses { return service.SpecUses{} }

// Describer resolves an instance for one call of a kind outside a run.
func (m *Module) Describer() api.Describer { return m.svc }

// Decider is the decision model call.
func (m *Module) Decider() api.Decider { return m.svc }

// Media is the image and video model calls.
func (m *Module) Media() api.Media { return m.svc }

// VideoJobs keeps the workspace's video generation jobs.
func (m *Module) VideoJobs() api.VideoJobs { return m.svc }

// Declared is the operator's writes of declared provider configurations.
func (m *Module) Declared() api.DeclaredProviders { return m.svc }
