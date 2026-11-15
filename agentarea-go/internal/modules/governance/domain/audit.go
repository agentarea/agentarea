package domain

import "time"

// AuditEvent is one audit_events row (AuditEventORM). Changes and Metadata
// are written; RawChanges and RawMetadata are the stored JSON read back.
type AuditEvent struct {
	ID           string
	CreatedAt    time.Time
	ActorID      string
	ActorType    string
	WorkspaceID  string
	SourceIP     *string
	UserAgent    *string
	RequestID    *string
	Action       string
	ResourceType string
	ResourceID   *string
	Changes      []map[string]any
	Metadata     map[string]any
	RawChanges   []byte
	RawMetadata  []byte
}

// AuditQuery filters an audit page (AuditRepository.query).
type AuditQuery struct {
	Action, ActorID, ResourceType, ResourceID *string
	Since, Until                              *time.Time
	Cursor                                    *[16]byte
	Limit                                     int
}
