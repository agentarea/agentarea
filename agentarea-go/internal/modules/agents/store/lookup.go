package store

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

//go:generate sqlc generate

// Lookup reads agents and skills by id inside the session's workspace.
type Lookup struct{}

func (Lookup) AgentExists(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	return New(s.Q()).AgentExists(ctx, AgentExistsParams{WorkspaceID: s.Workspace().ID(), ID: id})
}

func (Lookup) SkillExists(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	return New(s.Q()).SkillExists(ctx, SkillExistsParams{WorkspaceID: s.Workspace().ID(), ID: id})
}

func (Lookup) AgentNames(ctx context.Context, s db.Session, ids []uuid.UUID) (map[uuid.UUID]string, error) {
	rows, err := New(s.Q()).AgentNames(ctx, AgentNamesParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make(map[uuid.UUID]string, len(rows))
	for _, r := range rows {
		out[r.ID] = r.Name
	}
	return out, nil
}

func (Lookup) SkillNames(ctx context.Context, s db.Session, ids []uuid.UUID) (map[uuid.UUID]string, error) {
	rows, err := New(s.Q()).SkillNames(ctx, SkillNamesParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make(map[uuid.UUID]string, len(rows))
	for _, r := range rows {
		out[r.ID] = r.Name
	}
	return out, nil
}

// AgentIDBySlug is the id of the workspace's agent with slug; false when none.
func (Lookup) AgentIDBySlug(ctx context.Context, s db.Session, slug string) (uuid.UUID, bool, error) {
	id, err := New(s.Q()).AgentIDBySlug(ctx, AgentIDBySlugParams{WorkspaceID: s.Workspace().ID(), Slug: slug})
	if errors.Is(err, pgx.ErrNoRows) {
		return uuid.UUID{}, false, nil
	}
	if err != nil {
		return uuid.UUID{}, false, err
	}
	return id, true, nil
}
