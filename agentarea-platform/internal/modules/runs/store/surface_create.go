package store

import (
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// NewSurfaceTask is a task a caller or an event starts, with every
// provenance column.
type NewSurfaceTask struct {
	ID, AgentID, Description, Status, CreatedBy string
	Parameters, Metadata                        map[string]any
	ScheduledAt                                 *time.Time
	OriginType, OriginID, CorrelationID         string
	CausationID, ParentTaskID, SourceIdentity   string
	TaskDefinitionID                            string
	Depth                                       int32
}

// InsertSurfaceTask stores t; a task no event started begins its own correlation chain.
func InsertSurfaceTask(ctx context.Context, s db.Session, t NewSurfaceTask, now time.Time) error {
	id, err := parseUUID("task id", t.ID)
	if err != nil {
		return err
	}
	agentID, err := parseUUID("agent id", t.AgentID)
	if err != nil {
		return err
	}
	parent, err := nullUUID(t.ParentTaskID)
	if err != nil {
		return err
	}
	def, err := nullUUID(t.TaskDefinitionID)
	if err != nil {
		return err
	}
	params, err := json.Marshal(domain.Storable(t.Parameters))
	if err != nil {
		return err
	}
	meta, err := json.Marshal(domain.Storable(t.Metadata))
	if err != nil {
		return err
	}
	correlation := t.CorrelationID
	if correlation == "" {
		correlation = t.ID
	}
	return New(s.Q()).SurfaceInsertTask(ctx, SurfaceInsertTaskParams{
		ID: id, AgentID: agentID, Description: t.Description, Parameters: string(params), Status: t.Status,
		TaskMetadata: string(meta), WorkspaceID: s.Workspace().ID(), CreatedBy: t.CreatedBy, Now: naive(now),
		ScheduledAt: Timestamptz(deref(t.ScheduledAt)), OriginType: text(t.OriginType), OriginID: text(t.OriginID),
		CorrelationID: text(correlation), CausationID: text(t.CausationID), ParentTaskID: parent, Depth: t.Depth,
		TaskDefinitionID: def, SourceIdentity: text(t.SourceIdentity),
	})
}

func deref(t *time.Time) time.Time {
	if t == nil {
		return time.Time{}
	}
	return *t
}

// SetSurfaceTaskStatus writes a status and its error; failed stamps completed_at.
func SetSurfaceTaskStatus(ctx context.Context, s db.Session, taskID, status, errText string, now time.Time) (bool, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).SurfaceSetTaskStatus(ctx, SurfaceSetTaskStatusParams{Status: status, Error: text(errText), Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}

// SessionTask is a live task of a trigger session a follow-up may join.
type SessionTask struct {
	ID, Description, ExecutionID, CreatedBy string
	Parameters                              map[string]any
}

// ActiveInSession is find_active_in_session: newest first, at most five.
func ActiveInSession(ctx context.Context, s db.Session, agentID, triggerID, sessionKey string) ([]SessionTask, error) {
	aid, err := parseUUID("agent id", agentID)
	if err != nil {
		return nil, err
	}
	rows, err := New(s.Q()).SurfaceActiveInSession(ctx, SurfaceActiveInSessionParams{WorkspaceID: s.Workspace().ID(), AgentID: aid, TriggerID: triggerID, SessionKey: sessionKey})
	if err != nil {
		return nil, err
	}
	out := make([]SessionTask, len(rows))
	for i, r := range rows {
		out[i] = SessionTask{ID: r.ID.String(), Description: r.Description, ExecutionID: r.ExecutionID.String, CreatedBy: r.CreatedBy, Parameters: objectOf([]byte(r.Parameters))}
	}
	return out, nil
}

// OutlineEntry is one log row as a resume reads it.
type OutlineEntry struct {
	Seq        int64
	Kind, Role string
	ToolCalls  int
}

// ConversationOutline is the task's log in seq order, without bodies.
func ConversationOutline(ctx context.Context, s db.Session, taskID string) ([]OutlineEntry, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return nil, err
	}
	rows, err := New(s.Q()).SurfaceConversationOutline(ctx, SurfaceConversationOutlineParams{TaskID: id, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	out := make([]OutlineEntry, len(rows))
	for i, r := range rows {
		out[i] = OutlineEntry{Seq: int64(r.Seq), Kind: r.Kind, Role: r.Role, ToolCalls: int(r.ToolCalls)}
	}
	return out, nil
}

// NewEventID is a fresh log row id.
func NewEventID() string { return uuid.NewString() }
