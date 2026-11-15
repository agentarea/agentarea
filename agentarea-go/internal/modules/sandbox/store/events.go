package store

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
)

//go:generate sqlc generate

// Events reads and writes artifact_events inside the session's workspace.
type Events struct{}

func text(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

func fromText(t pgtype.Text) *string {
	if !t.Valid {
		return nil
	}
	s := t.String
	return &s
}

// Stamp is t as the UTC wall clock the naive column holds.
func Stamp(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.UTC().Truncate(time.Microsecond), Valid: true}
}

// Insert appends one provenance row stamped in UTC.
func (Events) Insert(ctx context.Context, s db.Session, e domain.ArtifactEvent) error {
	return New(s.Q()).InsertArtifactEvent(ctx, InsertArtifactEventParams{
		ID: uuid.New(), Now: Stamp(e.CreatedAt),
		WorkspaceID: s.Workspace().ID(), CreatedBy: e.CreatedBy, Path: e.Path, Action: e.Action,
		ActorType: e.ActorType, AgentID: text(e.AgentID), TaskID: text(e.TaskID),
	})
}

// History is every event of path in the workspace, newest first.
func (Events) History(ctx context.Context, s db.Session, path string) ([]domain.ArtifactEvent, error) {
	rows, err := New(s.Q()).ArtifactHistory(ctx, ArtifactHistoryParams{WorkspaceID: s.Workspace().ID(), Path: path})
	if err != nil {
		return nil, err
	}
	out := make([]domain.ArtifactEvent, len(rows))
	for i, r := range rows {
		out[i] = domain.ArtifactEvent{
			Path: path, Action: r.Action, ActorType: r.ActorType, CreatedBy: r.CreatedBy,
			AgentID: fromText(r.AgentID), TaskID: fromText(r.TaskID), CreatedAt: r.CreatedAt.Time,
		}
	}
	return out, nil
}

// Rename moves every event of source onto destination, so a moved file keeps
// its history.
func (Events) Rename(ctx context.Context, s db.Session, source, destination string, now time.Time) error {
	return New(s.Q()).RenameArtifactEvents(ctx, RenameArtifactEventsParams{
		Destination: destination, Now: Stamp(now), WorkspaceID: s.Workspace().ID(), Source: source,
	})
}
