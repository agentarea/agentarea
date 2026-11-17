package service

import (
	"context"
	"log/slog"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/store"
)

// Inventory implements api.Inventory over the read pool.
type Inventory struct{ DB db.Database }

var _ api.Inventory = Inventory{}

func (i Inventory) read(ctx context.Context, ws scope.Workspace, fn func(q *store.Queries, wsID string) error) error {
	s, release, err := i.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(store.New(s.Q()), s.Workspace().ID())
}

func (i Inventory) Agents(ctx context.Context, ws scope.Workspace, includeArchived bool) ([]api.Named, error) {
	out := []api.Named{}
	err := i.read(ctx, ws, func(q *store.Queries, wsID string) error {
		rows, err := q.InventoryAgents(ctx, store.InventoryAgentsParams{WorkspaceID: wsID, IncludeArchived: includeArchived})
		for _, r := range rows {
			out = append(out, api.Named{ID: r.ID.String(), Name: r.Name})
		}
		return err
	})
	return out, err
}

func (i Inventory) Skills(ctx context.Context, ws scope.Workspace) ([]api.Named, error) {
	out := []api.Named{}
	err := i.read(ctx, ws, func(q *store.Queries, wsID string) error {
		rows, err := q.InventorySkills(ctx, wsID)
		for _, r := range rows {
			out = append(out, api.Named{ID: r.ID.String(), Name: r.Name})
		}
		return err
	})
	return out, err
}

func (i Inventory) Collections(ctx context.Context, ws scope.Workspace) ([]api.Named, error) {
	out := []api.Named{}
	err := i.read(ctx, ws, func(q *store.Queries, wsID string) error {
		rows, err := q.ListCollections(ctx, wsID)
		for _, r := range rows {
			out = append(out, api.Named{ID: r.ID.String(), Name: r.Name})
		}
		return err
	})
	return out, err
}

func (i Inventory) SkillCounts(ctx context.Context, ws scope.Workspace) (map[string]int, error) {
	out := map[string]int{}
	err := i.read(ctx, ws, func(q *store.Queries, wsID string) error {
		rows, err := q.CollectionSkillCounts(ctx, wsID)
		for _, r := range rows {
			out[r.CollectionID.String()] = int(r.N)
		}
		return err
	})
	return out, err
}

func (i Inventory) CollectionExists(ctx context.Context, ws scope.Workspace, id uuid.UUID) (bool, error) {
	var ok bool
	err := i.read(ctx, ws, func(q *store.Queries, wsID string) error {
		var err error
		ok, err = q.CollectionExists(ctx, store.CollectionExistsParams{WorkspaceID: wsID, ID: id})
		return err
	})
	return ok, err
}

// CatalogUses implements api.CatalogUses; Graph revokes a dropped skill's tuples.
type CatalogUses struct {
	Graph authz.ReadWriter
	Log   *slog.Logger
}

var _ api.CatalogUses = CatalogUses{}

func (u CatalogUses) MoveItem(ctx context.Context, tx db.Session, oldID, newID uuid.UUID) (int, error) {
	q := store.New(tx.Q())
	forks, err := q.MoveSkillForks(ctx, store.MoveSkillForksParams{OldID: oldID, NewID: newID})
	if err != nil {
		return 0, err
	}
	agents, err := q.MoveAgentItems(ctx, store.MoveAgentItemsParams{OldID: oldID.String(), NewID: newID.String()})
	return int(forks + agents), err
}

func (u CatalogUses) ReferencedItems(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error) {
	out := map[uuid.UUID]bool{}
	if len(ids) == 0 {
		return out, nil
	}
	q := store.New(tx.Q())
	skills, err := q.SkillReferencedItems(ctx, ids)
	if err != nil {
		return nil, err
	}
	for _, id := range skills {
		out[id] = true
	}
	texts := make([]string, len(ids))
	for i, id := range ids {
		texts[i] = id.String()
	}
	agents, err := q.AgentReferencedItems(ctx, texts)
	if err != nil {
		return nil, err
	}
	for _, s := range agents {
		if id, err := uuid.Parse(s); err == nil {
			out[id] = true
		}
	}
	return out, nil
}

func (u CatalogUses) DropPlatformSkills(ctx context.Context, tx db.Session, ids []uuid.UUID) error {
	if len(ids) == 0 {
		return nil
	}
	deleted, err := store.New(tx.Q()).DeletePlatformSkills(ctx, ids)
	if err != nil {
		return err
	}
	if u.Graph == nil {
		return nil
	}
	for _, id := range deleted {
		if err := authz.RevokeResource(ctx, u.Graph, id.String()); err != nil && u.Log != nil {
			u.Log.WarnContext(ctx, "revoking a dropped platform skill's tuples failed", "skill_id", id.String(), "error", err.Error())
		}
	}
	return nil
}
