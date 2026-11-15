// Package agents is the agents module: agents, clients (registered harnesses), skills and task definitions; A2A.
package agents

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	govapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// Deps are what agents needs from other modules and the kernel, as interfaces
// declared in its service/deps.go; app passes them in (rule 2). A nil port
// leaves the feature that needs it answering 501.
type Deps struct {
	DB db.Database
	// Graph is the authorization graph: it must be a full authz.Graph for the HTTP
	// routes; nil mounts them for route listing only.
	Graph       authz.Writer
	Models      service.Models
	Approvals   service.Approvals
	Connections service.Connections
	Presence    service.Presence
	CodeTools   service.CodeTools
	// Triggers makes the triggers sent with a new agent (streams); nil answers 501 for them.
	Triggers service.AgentTriggers
	Config   Config
	// Audit writes the audit trail (governance); nil leaves it unwritten.
	Audit govapi.AuditWriter
	// Blob is the artifacts bucket (skill packages).
	Blob blob.Store
	// Workspace admits the caller into /v1/workspaces/{workspace} and puts
	// it in the request context (authn.CallerFrom).
	Workspace func(http.Handler) http.Handler
	// Principal authenticates a request outside a workspace path (authn.PrincipalFrom).
	Principal func(http.Handler) http.Handler
	// Admin refuses a caller in ctx who is not an admin of its workspace.
	Admin func(ctx context.Context) error
	Log   *slog.Logger
	Now   func() time.Time

	SkillDeps
	ClientDeps
	TaskDefDeps
	A2ADeps
	MiscDeps
}

// Module is agents, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d      Deps
	lookup *service.Lookup
	svc    *service.Service
}

// New constructs the module.
func New(d Deps) *Module {
	if d.Log == nil {
		d.Log = slog.New(slog.DiscardHandler)
	}
	m := &Module{d: d, lookup: &service.Lookup{DB: d.DB}}
	if g, ok := d.Graph.(service.Graph); ok || d.Graph == nil {
		m.svc = service.New(service.Deps{
			DB: d.DB, Graph: g, Models: d.Models, Approvals: d.Approvals, Connections: d.Connections,
			Presence: d.Presence, CodeTools: d.CodeTools, Triggers: d.Triggers, A2AAgentURL: d.Config.A2AAgentURL, Now: d.Now,
			Audit: d.Audit, Admin: d.Admin, Log: d.Log,
		})
	}
	return m
}

// Name is the module's name in the role table.
func (*Module) Name() string { return "agents" }

// Lookup is what other modules read about agents and skills.
func (m *Module) Lookup() api.Lookup { return m.lookup }

// Inventory lists agents, skills and collections for the access explorer.
func (m *Module) Inventory() api.Inventory { return service.Inventory{DB: m.d.DB} }

// CatalogUses is what a catalog sync does to skills and agents made from its items.
func (m *Module) CatalogUses() api.CatalogUses {
	u := service.CatalogUses{Log: m.d.Log}
	if rw, ok := m.d.Graph.(authz.ReadWriter); ok {
		u.Graph = rw
	}
	return u
}

// Definitions is what runs reads to resolve a run's agent; nil without a full graph.
func (m *Module) Definitions() api.Definitions {
	if m.svc == nil {
		return nil
	}
	return service.Definitions{Service: m.svc}
}

// Serve is the module's HTTP surface.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			if m.svc == nil {
				return fmt.Errorf("agents: the graph passed to agents.New is not a full authz.Graph")
			}
			extras := m.extras()
			extras.MaxBody = rt.MaxBody
			handlers.Mount(rt.Mux.Chi(), rt.Errors, handlers.Edge{Workspace: m.d.Workspace, Principal: m.d.Principal},
				handlers.New(m.svc, extras))
			return nil
		},
	}
}

// extras are the services of the route groups beyond agents and collections.
func (m *Module) extras() handlers.Extras {
	return handlers.Extras{
		Skills:   m.skills(),
		Clients:  m.clients(),
		TaskDefs: m.taskDefs(),
		A2A:      m.a2a(),
		Misc:     m.misc(),
	}
}

// AgentsToolset is what the platform MCP agents toolset calls; nil without a full graph.
func (m *Module) AgentsToolset() api.Agents {
	if m.svc == nil {
		return nil
	}
	return handlers.AgentsToolset{Svc: m.svc}
}

// Later are the ports of modules app builds after agents.
type Later struct {
	Audit          govapi.AuditWriter
	ClientMCPNames service.ClientMCPNames
	// Models validates model_id; Connections binds MCP names and lends connections.
	Models      service.Models
	Connections service.Connections
	// ClientRunnerKeys issues runner keys (identity); nil keeps the one Deps gave.
	ClientRunnerKeys service.ClientRunnerKeys
	// Approvals are the agent editor's approval rules (governance); nil keeps the one Deps gave.
	Approvals service.Approvals
	// Catalog is the catalog's agent and skill items; InstallPolicy decides on installing them (governance).
	Catalog       service.CatalogItems
	InstallPolicy service.SkillInstallPolicy
}

// Use sets the ports of modules built after agents; call it before serving.
// A nil Models or Connections keeps the one Deps gave.
func (m *Module) Use(l Later) {
	m.d.Audit = l.Audit
	m.d.ClientMCPNames = l.ClientMCPNames
	if l.Models != nil {
		m.d.Models = l.Models
	}
	if l.Connections != nil {
		m.d.Connections = l.Connections
	}
	if l.ClientRunnerKeys != nil {
		m.d.ClientRunnerKeys = l.ClientRunnerKeys
	}
	if l.Approvals != nil {
		m.d.Approvals = l.Approvals
	}
	if l.Catalog != nil {
		m.d.CatalogItems = l.Catalog
	}
	if l.InstallPolicy != nil {
		m.d.SkillInstallPolicy = l.InstallPolicy
	}
	if m.svc != nil {
		m.svc.UseAudit(l.Audit)
		m.svc.UseModels(m.d.Models)
		m.svc.UseConnections(m.d.Connections)
		m.svc.UseApprovals(m.d.Approvals)
	}
}
