package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/store"
)

// Lookup implements api.Lookup over the read pool. An id that is not a UUID
// names nothing.
type Lookup struct {
	DB    db.Database
	store store.Lookup
}

var _ api.Lookup = (*Lookup)(nil)

func (l *Lookup) read(ctx context.Context, ws scope.Workspace, fn func(s db.Session) error) error {
	s, release, err := l.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(s)
}

func (l *Lookup) exists(ctx context.Context, ws scope.Workspace, id string,
	query func(context.Context, db.Session, uuid.UUID) (bool, error)) (bool, error) {
	parsed, err := uuid.Parse(id)
	if err != nil {
		return false, nil
	}
	var ok bool
	err = l.read(ctx, ws, func(s db.Session) error {
		ok, err = query(ctx, s, parsed)
		return err
	})
	return ok, err
}

func (l *Lookup) names(ctx context.Context, ws scope.Workspace, ids []string,
	query func(context.Context, db.Session, []uuid.UUID) (map[uuid.UUID]string, error)) (map[string]string, error) {
	out := map[string]string{}
	parsed := make([]uuid.UUID, 0, len(ids))
	for _, id := range ids {
		if u, err := uuid.Parse(id); err == nil {
			parsed = append(parsed, u)
		}
	}
	if len(parsed) == 0 {
		return out, nil
	}
	err := l.read(ctx, ws, func(s db.Session) error {
		found, err := query(ctx, s, parsed)
		for id, name := range found {
			out[id.String()] = name
		}
		return err
	})
	return out, err
}

func (l *Lookup) AgentExists(ctx context.Context, ws scope.Workspace, id string) (bool, error) {
	return l.exists(ctx, ws, id, l.store.AgentExists)
}

func (l *Lookup) SkillExists(ctx context.Context, ws scope.Workspace, id string) (bool, error) {
	return l.exists(ctx, ws, id, l.store.SkillExists)
}

func (l *Lookup) AgentNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error) {
	return l.names(ctx, ws, ids, l.store.AgentNames)
}

func (l *Lookup) SkillNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error) {
	return l.names(ctx, ws, ids, l.store.SkillNames)
}

func (l *Lookup) AgentIDBySlug(ctx context.Context, ws scope.Workspace, slug string) (string, bool, error) {
	var id uuid.UUID
	var ok bool
	err := l.read(ctx, ws, func(s db.Session) error {
		var err error
		id, ok, err = l.store.AgentIDBySlug(ctx, s, slug)
		return err
	})
	if err != nil || !ok {
		return "", false, err
	}
	return id.String(), true, nil
}
