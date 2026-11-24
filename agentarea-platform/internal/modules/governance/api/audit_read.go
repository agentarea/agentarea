package api

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// AuditEntry is one stored audit row as a reader sees it; Metadata is the
// stored event_metadata JSON.
type AuditEntry struct {
	ID         string
	CreatedAt  time.Time
	ActorType  string
	ActorID    string
	Action     string
	ResourceID string
	Metadata   []byte
}

// AuditPage asks for one page of a resource type's rows with one of Actions,
// newest first (AuditRepository.resource_events_page).
type AuditPage struct {
	ResourceType  string
	Actions       []string
	Limit, Offset int
}

// AuditReader reads audit rows in the caller's session, with the total that
// matches.
type AuditReader interface {
	ResourceEvents(ctx context.Context, s db.Session, q AuditPage) ([]AuditEntry, int64, error)
}
