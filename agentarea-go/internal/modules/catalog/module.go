// Package catalog is the catalog module: registries, registry items, provider and model specs, MCP server specs, bundles; catalog sync.
package catalog

import (
	"context"
	"log/slog"
	"net/http"
	"net/url"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// Deps are what catalog needs from other modules and the kernel, as interfaces
// declared in its service/deps.go; app passes them in (rule 2).
type Deps struct {
	DB db.Database
	// Authority decides the platform catalog write (can_write_workspace on
	// the platform workspace).
	Authority service.Authority
	// Connections and Pricing render a connection's card; without both,
	// browse and the item card stay unmounted.
	Connections service.CatalogConnections
	Pricing     service.CatalogPricing
	// Workspace admits the caller into /v1/workspaces/{workspace}.
	Workspace func(http.Handler) http.Handler
	// Admin is requires_workspace_admin; nil leaves the admin writes unmounted.
	Admin func(ctx context.Context) error
	// Guard is the outbound address policy a workspace registry's index URL
	// must pass; read when a URL is checked.
	Guard func() *netguard.Guard
	// Secrets binds the secret catalog to a caller; nil leaves the
	// workspace-registry writes unmounted.
	Secrets func(ws scope.Workspace, actor ksecrets.Actor) SecretUse
	// APIURL is the base built-in provider icons are served from.
	APIURL string
	Log    *slog.Logger
	Now    func() time.Time
	// Uses are the rows agents, connections and models hold that name
	// catalog items and specs; with Net, sync, retire and reconcile need it.
	Uses api.ItemUses
	// Net hands out the outbound clients sources are read through.
	Net netguard.Clients
	// GitHub is where GitHub is reached; zero is github.com.
	GitHub service.GitHubEndpoints
	// Mirror stores mirror-mode skills content; nil fails such a sync.
	Mirror api.ContentMirror
	// Credentials resolves a registry's credentials reference at sync time.
	Credentials api.RegistryCredentials
	// PlatformSecrets resolves and records a manifest's credentials.
	PlatformSecrets api.PlatformSecrets
	// RateLimit is the workspace-registry sync's limiter; nil leaves that
	// route unmounted.
	RateLimit httpx.RateLimiter
}

// SecretUse is the part of the secret catalog a workspace registry's
// credentials need.
type SecretUse = service.SecretUse

// SpecUse is models' answer to which specs a workspace has put to use.
type SpecUse = service.SpecUse

// Module is catalog, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d          Deps
	svc        *service.Service
	bundles    *service.Bundles
	bundlesErr error
}

// New constructs the module.
func New(d Deps) *Module {
	sd := service.Deps{
		DB: d.DB, Specs: store.Specs{}, Registries: store.Registries{}, Authority: d.Authority,
		APIURL: d.APIURL, Log: d.Log, Now: d.Now,
		Sync: store.Sync{}, Uses: d.Uses, Mirror: d.Mirror, Credentials: d.Credentials, PlatformSecrets: d.PlatformSecrets,
	}
	if d.Net != nil {
		gh := d.GitHub
		if gh == (service.GitHubEndpoints{}) {
			gh = service.DefaultGitHub()
		}
		sd.Fetch = service.Fetcher{Net: d.Net, GitHub: gh}
	}
	if d.Secrets != nil {
		sd.Secrets = func(ws scope.Workspace, a ksecrets.Actor) service.SecretUse { return d.Secrets(ws, a) }
	}
	if g := d.Guard; g != nil {
		sd.PublicHTTPS = func(ctx context.Context, raw string) bool {
			u, err := url.Parse(raw)
			if err != nil || u.Scheme != "https" {
				return false
			}
			_, err = g().CheckURL(ctx, raw)
			return err == nil
		}
	}
	return &Module{d: d, svc: service.New(sd)}
}

// UseModels hands catalog models' spec use, which the provider-spec lists
// read; models is built after catalog.
func (m *Module) UseModels(u SpecUse) { m.svc.UseModels(u) }

// Name is the module's name in the role table.
func (*Module) Name() string { return "catalog" }

// Specs is what models reads and writes of provider and model specs.
func (m *Module) Specs() api.Specs { return m.svc.Specs() }

// SourceTypes is the catalog's event source types (streams reads them).
func (m *Module) SourceTypes() api.SourceTypes { return service.SourceTypes{DB: m.d.DB} }

// MCPSpecs is what connections reads and writes of MCP server specs.
func (m *Module) MCPSpecs() api.MCPSpecs { return m.svc.MCPSpecs() }

// MCPInventory lists a workspace's own MCP server specs for the access explorer.
func (m *Module) MCPInventory() api.MCPInventory { return service.MCPInventory{DB: m.d.DB} }

// APIItems is what connections reads of one-click API catalog items.
func (m *Module) APIItems() api.APIItems { return m.svc }

// Reconcile is the operator role's catalog reconcile.
func (m *Module) Reconcile() api.Reconciler { return m.svc }

// Serve is the module's HTTP surface.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			if m.bundlesErr != nil {
				return m.bundlesErr
			}
			handlers.Mount(rt.Mux.Chi(), rt.Errors, m.d.Workspace, handlers.New(m.svc, m.d.Connections, m.d.Pricing, m.d.Admin).WithRateLimit(m.d.RateLimit, m.d.Log).WithBundles(m.bundles))
			return nil
		},
	}
}

// Platform is the operator's writes of platform-declared catalog rows.
func (m *Module) Platform() api.PlatformDeclarations { return m.svc.Platform() }
