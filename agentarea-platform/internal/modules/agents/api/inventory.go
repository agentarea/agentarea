package api

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// Named is a row's id and name.
type Named struct{ ID, Name string }

// Inventory lists a workspace's agents, skills and skill collections as the
// access explorer reads them (AgentRepository, SkillRepository,
// SkillCollectionRepository list_all).
type Inventory interface {
	// Agents is list_all newest first; without includeArchived it leaves out
	// archived agents and harness clients' own agents.
	Agents(ctx context.Context, ws scope.Workspace, includeArchived bool) ([]Named, error)
	Skills(ctx context.Context, ws scope.Workspace) ([]Named, error)
	// Collections is newest first.
	Collections(ctx context.Context, ws scope.Workspace) ([]Named, error)
	// SkillCounts maps each collection id to how many skills it holds.
	SkillCounts(ctx context.Context, ws scope.Workspace) (map[string]int, error)
	CollectionExists(ctx context.Context, ws scope.Workspace, id uuid.UUID) (bool, error)
}

// CatalogUses is what a catalog sync does to the skills and agents that name
// catalog items; every method runs in the sync's transaction across workspaces.
type CatalogUses interface {
	// MoveItem points the forks of old at new (except where a workspace
	// already forked new) and the agents made from old; how many rows moved.
	MoveItem(ctx context.Context, tx db.Session, oldID, newID uuid.UUID) (int, error)
	// ReferencedItems are those of ids a skill or an agent names.
	ReferencedItems(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error)
	// DropPlatformSkills deletes the platform workspace's skill rows ids and
	// revokes their tuples.
	DropPlatformSkills(ctx context.Context, tx db.Session, ids []uuid.UUID) error
}
