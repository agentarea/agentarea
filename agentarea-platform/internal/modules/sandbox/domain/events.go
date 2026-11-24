package domain

import "time"

// Artifact event actions and actor types (artifacts/audit.py).
const (
	ActionCreated  = "created"
	ActionModified = "modified"
	ActionDeleted  = "deleted"
	ActionArchived = "archived"
	ActionMoved    = "moved"

	ActorUser  = "user"
	ActorAgent = "agent"
)

// ArtifactEvent is one artifact_events row.
type ArtifactEvent struct {
	Path      string
	Action    string
	ActorType string
	CreatedBy string
	AgentID   *string
	TaskID    *string
	CreatedAt time.Time
}
