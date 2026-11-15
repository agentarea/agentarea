// Package connections is the connections module: MCP server instances, auth configs and OAuth, OpenAPI connections, the MCP gateway and workloads.
package connections

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/mcpserver"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store"
	walletapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// Deps are what connections needs from other modules and the kernel, as interfaces
// declared in its service/deps.go; app passes them in (rule 2). A nil port leaves
// the routes that need it unmounted.
type Deps struct {
	DB db.Database
	// Graph is the authorization graph: the OpenAPI sharing and delete permission.
	Graph service.Graph
	// Secrets is the secret store's backend; Catalog the workspace catalog (reference clearing).
	Secrets service.Secrets
	Catalog service.Catalog
	// Workspace admits the caller into /v1/workspaces/{workspace} and puts
	// it in the request context (authn.CallerFrom).
	Workspace func(http.Handler) http.Handler
	// Admin refuses a caller in ctx who is not an admin of its workspace.
	Admin func(ctx context.Context) error
	// Specs is catalog's MCP server specs (catalogMod.MCPSpecs()).
	Specs service.Specs
	// Runtime is the in-process MCP runtime (connections/runtime, gateway).
	Runtime service.Runtime
	// Agents scans agents' saved tools; Policies reads governance's tool policy.
	Agents   service.AgentTools
	Policies service.ToolPolicies
	// Approvals reads agents' approval rules (governance) for /consumers.
	Approvals service.AgentApprovals
	// APIItems is catalog's one-click API items.
	APIItems catalogapi.APIItems
	// Out is the outbound HTTP; KV the OAuth state store (Redis).
	Out    service.Outbound
	KV     service.KV
	Config Config
	// Lookup, when set, reads Config from the environment (os.LookupEnv);
	// a bad value fails Serve.
	Lookup func(string) (string, bool)
	// Gate resolves bearer tokens and workspace entry for the MCP surfaces;
	// Authenticate is get_principal on a route that names no workspace.
	Gate         authn.Gate
	Authenticate func(http.Handler) http.Handler
	// ClientBundles is agents' read of a client's attachments (/mcp/clients);
	// Audit governance's audit writer for the client endpoint's tool calls;
	// Toolsets the providers of the platform toolsets /mcp serves.
	ClientBundles service.ClientBundles
	Audit         service.AuditWriter
	Toolsets      mcpserver.Providers
	// APIURL and AppURL are the public bases of the API and the webapp.
	APIURL string
	AppURL string
	Log    *slog.Logger
	Now    func() time.Time
}

// Module is connections, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d       Deps
	svc     *service.Service
	lookup  *service.Lookup
	loadErr error
	// toolsets is Later.Toolsets, read when serving and calling.
	toolsets *Toolsets
	wallets  walletapi.Wallets
}

// New constructs the module.
func New(d Deps) *Module {
	m := &Module{d: d, lookup: &service.Lookup{DB: d.DB, Store: store.Lookup{}}}
	if d.Lookup != nil {
		l := config.New(d.Lookup)
		m.d.Config = LoadConfig(l)
		m.loadErr = l.Err()
	}
	m.build()
	return m
}

// Later are the ports of modules app builds after connections.
type Later struct {
	Specs     service.Specs
	Policies  service.ToolPolicies
	Approvals service.AgentApprovals
	Audit     service.AuditWriter
	// APIItems is catalog's one-click API items (OpenAPI from-catalog, OAuth connect).
	APIItems catalogapi.APIItems
	// Toolsets, when set, replaces Deps.Toolsets. It is read when /mcp is
	// mounted and when a run calls a tool, so app sets the providers of
	// modules it builds after connections on it before serving.
	Toolsets *Toolsets
}

// Toolsets are the providers of the platform toolsets /mcp serves; a nil
// provider leaves its toolset unserved.
type Toolsets = mcpserver.Providers

// Use sets the ports of modules built after connections; call it before
// serving or starting anything of the module.
func (m *Module) Use(l Later) {
	m.d.Specs, m.d.Policies, m.d.Approvals, m.d.Audit = l.Specs, l.Policies, l.Approvals, l.Audit
	m.d.APIItems = l.APIItems
	m.toolsets = l.Toolsets
	m.build()
}

// UseWallets sets the agents' wallets runs' calls pay their 402s from; wallet
// is built after connections.
func (m *Module) UseWallets(w walletapi.Wallets) {
	m.wallets = w
	m.svc.UseWallets(w)
}

func (m *Module) providers() Toolsets {
	if m.toolsets != nil {
		return *m.toolsets
	}
	return m.d.Toolsets
}

func (m *Module) build() {
	d := m.d
	var items service.CatalogItems
	if d.APIItems != nil {
		items = catalogItems{items: d.APIItems}
	}
	m.svc = service.New(service.Deps{
		DB: d.DB, Auth: store.Auth{}, Links: store.Links{}, Connections: store.OpenAPI{}, OpenAPIWrites: store.OpenAPI{},
		Instances: store.Instances{}, Secrets: d.Secrets, Catalog: d.Catalog, Graph: d.Graph,
		Specs: d.Specs, Runtime: d.Runtime, Agents: d.Agents, Policies: d.Policies, Approvals: d.Approvals, Out: d.Out, KV: d.KV,
		Config: d.Config, Admin: d.Admin, APIURL: d.APIURL, AppURL: d.AppURL, Log: d.Log, Now: d.Now,
		ClientBundles: d.ClientBundles, Audit: d.Audit,
		Wallets:      m.wallets,
		OAuthStore:   store.OAuthConnect{},
		CatalogItems: items,
	})
}

// Name is the module's name in the role table.
func (*Module) Name() string { return "connections" }

// Lookup is what other modules read about MCP server instances, OpenAPI
// connections and their platform flags.
func (m *Module) Lookup() api.Lookup { return m.lookup }

// Loans binds agents' MCP tool names and lends connections to agents; nil
// when Deps.Graph cannot write.
func (m *Module) Loans() api.Loans {
	w, ok := m.d.Graph.(authz.Writer)
	if !ok {
		return nil
	}
	return service.Loans{DB: m.d.DB, Store: store.Lookup{}, Graph: w}
}

// Serve is the module's HTTP surface.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			if m.loadErr != nil {
				return m.loadErr
			}
			if m.d.Workspace == nil || m.d.Admin == nil {
				return nil
			}
			toolsets, err := m.providers().Toolsets(m.d.APIURL)
			if err != nil {
				return err
			}
			handlers.Mount(rt.Mux.Chi(), rt.Errors,
				handlers.Edge{Workspace: m.d.Workspace, Admin: m.d.Admin, Gate: m.d.Gate, Authenticate: m.d.Authenticate},
				handlers.New(m.svc),
				handlers.Ports{OpenAPI: m.d.Graph != nil && m.d.Secrets != nil && m.d.Catalog != nil, MCPToolsets: toolsets})
			return nil
		},
	}
}

// Monitor is the container monitor (stale verifications, never-attempted
// sweep, package imports); the worker runs it.
func (m *Module) Monitor() lifecycle.Component {
	return lifecycle.Loop("mcp-container-monitor", func(ctx context.Context) error { return m.svc.RunMonitor(ctx) })
}

// DispatchStamps writes the last-call stamps of MCP instances; every process
// that calls tools runs it.
func (m *Module) DispatchStamps() lifecycle.Component {
	return lifecycle.Loop("mcp-dispatch-stamps", func(ctx context.Context) error { return m.svc.RunDispatchStamps(ctx) })
}

// MCPExports lists the MCP server instances for the workspace config export.
func (m *Module) MCPExports() api.MCPExports { return moduleExports{m} }

type moduleExports struct{ m *Module }

func (e moduleExports) ExportInstances(ctx context.Context, c authn.Caller) ([]api.ExportInstance, error) {
	return e.m.svc.ExportInstances(ctx, c)
}

// MCPTools is the MCP tool call path runs use.
func (m *Module) MCPTools() api.MCPTools { return moduleTools{m} }

type moduleTools struct{ m *Module }

func (t moduleTools) Call(ctx context.Context, call api.MCPCall) (api.MCPResult, error) {
	return t.m.svc.MCPTools().Call(ctx, call)
}

// SettledCosts reads a settled call's cost declaration and its vendor's
// figure; it reads the service current when called, so Use may come later.
func (m *Module) SettledCosts() api.SettledCosts { return settledCosts{m} }

type settledCosts struct{ m *Module }

func (c settledCosts) SettledDeclaration(ctx context.Context, ws scope.Workspace, userID, connectionID, tool string) (map[string]any, error) {
	return c.m.svc.SettledDeclaration(ctx, ws, userID, connectionID, tool)
}

func (c settledCosts) FetchSettlement(ctx context.Context, ws scope.Workspace, userID, connectionID, url string) (int, []byte, error) {
	return c.m.svc.FetchSettlement(ctx, ws, userID, connectionID, url)
}
