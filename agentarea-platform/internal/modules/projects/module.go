// Package projects is the projects module: projects and what they group: agents, skills, MCP instances.
package projects

import (
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

// Deps are what projects needs from other modules and the kernel, as interfaces
// declared in its service/deps.go; app passes them in (rule 2).
type Deps struct {
	DB          db.Database
	Agents      service.Agents
	Connections service.Connections
	// Files is the sandbox's store; nil leaves the five file routes unmounted.
	Files service.Files
	// APIURL is AGENTAREA_API_URL.
	APIURL string
	// Workspace admits the caller into /v1/workspaces/{workspace} and puts
	// it in the request context (authn.CallerFrom).
	Workspace func(http.Handler) http.Handler
	Now       func() time.Time
}

// Module is projects, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d   Deps
	svc *service.Service
}

// New constructs the module.
func New(d Deps) *Module {
	return &Module{d: d, svc: service.New(service.Deps{
		DB: d.DB, Store: store.Projects{}, Agents: d.Agents, Connections: d.Connections,
		Files: d.Files, APIURL: d.APIURL, Now: d.Now,
	})}
}

// Lookup is what other modules read about projects.
func (m *Module) Lookup() api.Lookup { return m.svc }

// RunInstructions is what a run reads of its project's instructions.
func (m *Module) RunInstructions() api.RunInstructions { return m.svc }

// Name is the module's name in the role table.
func (*Module) Name() string { return "projects" }

// Serve is the module's HTTP surface.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			handlers.Mount(rt.Mux.Chi(), rt.Errors, m.d.Workspace, handlers.New(m.svc), m.d.Files != nil)
			return nil
		},
	}
}
