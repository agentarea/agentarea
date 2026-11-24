package service

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/domain"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// Store is the projects repository (store.Projects).
type Store interface {
	Create(ctx context.Context, s db.Session, id uuid.UUID, createdBy string, n domain.New, now time.Time) (domain.Project, error)
	Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Project, bool, error)
	List(ctx context.Context, s db.Session, limit, offset int32) ([]domain.Project, error)
	Node(ctx context.Context, s db.Session, id uuid.UUID) (domain.Node, bool, error)
	Update(ctx context.Context, s db.Session, id uuid.UUID, p domain.Patch, now time.Time) (bool, error)
	Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
	Links(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]*domain.Links, error)
	Link(ctx context.Context, s db.Session, k domain.LinkKind, project, child uuid.UUID) error
	Unlink(ctx context.Context, s db.Session, k domain.LinkKind, project, child uuid.UUID) error
	AgentProjects(ctx context.Context, s db.Session, agentID uuid.UUID) ([]uuid.UUID, error)
}

// Agents reads agents and skills (agents module).
type Agents = agentsapi.Lookup

// Connections reads MCP server instances (connections module).
type Connections = connectionsapi.Lookup

// Files is the workspace file store (sandbox module).
type Files = sandboxapi.Files

// Deps are the service's ports.
type Deps struct {
	DB          db.Database
	Store       Store
	Agents      Agents
	Connections Connections
	// Files is nil until sandbox implements it; the file routes are not
	// mounted without it.
	Files Files
	// APIURL is AGENTAREA_API_URL, the base of file download URLs.
	APIURL string
	// Now is the wall clock project timestamps are written in; nil is time.Now.
	Now func() time.Time
}
