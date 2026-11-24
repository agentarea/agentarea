// Package connections is the connections module: MCP server instances, auth configs and OAuth, OpenAPI connections, the MCP gateway and workloads.
package connections

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/mcpclient"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/mcpserver"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/store"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	walletapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
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
	// Counter counts connector checks and OAuth connects for usage analytics; nil counts nothing.
	Counter analytics.Counter
	// RateLimit limits anonymous OAuth client registration per address;
	// required when the authorization-server routes are served.
	RateLimit httpx.RateLimiter
}

// Module is connections, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d      Deps
	svc    *service.Service
	lookup *service.Lookup
	// stamps and verdicts outlive the Service that Use rebuilds.
	stamps   *service.Stamps
	verdicts *mcpclient.Verdicts
	// toolsets is Later.Toolsets, read when serving and calling.
	toolsets    *Toolsets
	wallets     walletapi.Wallets
	heldCalls   runsapi.HeldCalls
	clientCalls runsapi.ClientToolCalls
	egressExits service.EgressExitBinding
}

// New constructs the module.
func New(d Deps) *Module {
	m := &Module{d: d, lookup: &service.Lookup{DB: d.DB, Store: store.Lookup{}},
		stamps: service.NewStamps(), verdicts: service.NewVerdicts()}
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
	// EgressExits is governance's binding check, set only where the edition
	// enforces egress exits.
	EgressExits service.EgressExitBinding
}

// Toolsets are the providers of the platform toolsets /mcp serves; a nil
// provider leaves its toolset unserved.
type Toolsets = mcpserver.Providers

// Use sets the ports of modules built after connections; call it before
// serving or starting anything of the module.
func (m *Module) Use(l Later) {
	m.d.Specs, m.d.Policies, m.d.Approvals, m.d.Audit = l.Specs, l.Policies, l.Approvals, l.Audit
	m.d.APIItems = l.APIItems
	m.egressExits = l.EgressExits
	m.toolsets = l.Toolsets
	m.build()
}

// UseTaskFiles sets runs' signed downloads of a turn's task files; runs is built after connections.
func (m *Module) UseTaskFiles(f runsapi.TaskFileURLs) { m.svc.UseTaskFiles(f) }

// UseHeldCalls sets runs' approval gate of held calls; runs is built after connections.
func (m *Module) UseHeldCalls(h runsapi.HeldCalls) {
	m.heldCalls = h
	m.svc.UseHeldCalls(h)
}

// UseClientCalls sets runs' pricing, caps and metering of calls outside a run; runs is built
// after connections.
func (m *Module) UseClientCalls(c runsapi.ClientToolCalls) {
	m.clientCalls = c
	m.svc.UseClientCalls(c)
}

// ToolCosts reads what a connection declares a tool call costs, when the call is made.
func (m *Module) ToolCosts() runsapi.ToolCosts { return m.svc }

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
		Config: d.Config, Stamps: m.stamps, Verdicts: m.verdicts, Admin: d.Admin, APIURL: d.APIURL, AppURL: d.AppURL, Log: d.Log, Now: d.Now,
		ClientBundles: d.ClientBundles, Audit: d.Audit, Counter: d.Counter,
		Wallets:      m.wallets,
		HeldCalls:    m.heldCalls,
		ClientCalls:  m.clientCalls,
		EgressExits:  m.egressExits,
		OAuthStore:   store.OAuthConnect{},
		CatalogItems: items,
	})
}

// Name is the module's name in the role table.
func (*Module) Name() string { return "connections" }

// Lookup is what other modules read about MCP server instances, OpenAPI
// connections and their platform flags.
func (m *Module) Lookup() api.Lookup { return m.lookup }

// Attachable is what attaching a connection to a client reads.
func (m *Module) Attachable() api.Attachable { return m.lookup }

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
			if m.d.Workspace == nil || m.d.Admin == nil {
				return nil
			}
			if m.svc.OAuthASReady() && m.d.RateLimit == nil {
				return errors.New("connections: anonymous OAuth client registration (POST /oauth2/register) needs a rate limiter; none is wired")
			}
			toolsets, err := m.providers().Toolsets(m.d.APIURL)
			if err != nil {
				return err
			}
			handlers.Mount(rt.Mux.Chi(), rt.Errors,
				handlers.Edge{Workspace: m.d.Workspace, Admin: m.d.Admin, Gate: m.d.Gate, Authenticate: m.d.Authenticate},
				handlers.New(m.svc).WithRateLimit(m.d.RateLimit, m.d.Log),
				handlers.Ports{OpenAPI: m.d.Graph != nil && m.d.Secrets != nil && m.d.Catalog != nil, MCPToolsets: toolsets,
					Events: m.providers().EventsServer()})
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

// CatalogConnections lists the caller's connections per catalog item; catalog
// takes it before Use rebuilds the service, so it reads the service when called.
func (m *Module) CatalogConnections() api.CatalogConnections { return catalogConnections{m} }

type catalogConnections struct{ m *Module }

func (c catalogConnections) CatalogConnections(ctx context.Context, caller authn.Caller, itemIDs []string) (map[string][]api.CatalogConnection, error) {
	return c.m.svc.CatalogConnections(ctx, caller, itemIDs)
}

// EgressBindings is what egress exits read and do of the instances bound to
// one; it reads the service when called, as Use rebuilds it.
func (m *Module) EgressBindings() api.EgressBindings { return egressBindings{m} }

type egressBindings struct{ m *Module }

func (e egressBindings) BoundToEgressExit(ctx context.Context, ws scope.Workspace, exitID string) ([]api.EgressBoundInstance, error) {
	return e.m.svc.BoundToEgressExit(ctx, ws, exitID)
}

func (e egressBindings) RetireBeforeMutation(ctx context.Context, instanceID string) error {
	return e.m.svc.RetireBeforeMutation(ctx, instanceID)
}

// MCPToolCatalogue lists the MCP tools GET /agents/tools shows.
func (m *Module) MCPToolCatalogue() api.MCPToolCatalogue { return m.svc }

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

// MCPEventSources reads the instances an MCP Events source may name.
func (m *Module) MCPEventSources() api.MCPEventSources { return m.svc }

// Platform is the operator's writes of platform-declared connections.
func (m *Module) Platform() api.PlatformConnections { return m.svc }
