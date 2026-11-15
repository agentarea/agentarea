package service

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
)

// TaskDefs serves the task definition routes.
type TaskDefs struct {
	s *Service
	p TaskDefPorts
}

// NewTaskDefs builds the service over the agents service.
func NewTaskDefs(s *Service, p TaskDefPorts) *TaskDefs { return &TaskDefs{s: s, p: p} }

// TaskDefNotFoundError is TaskDefinitionNotFoundError (a 404).
type TaskDefNotFoundError struct{ ID uuid.UUID }

func (e *TaskDefNotFoundError) Error() string {
	return fmt.Sprintf("Task definition %s not found", e.ID)
}

// TaskDefInvalidError is TaskDefinitionValidationError (a 400).
type TaskDefInvalidError struct{ Msg string }

func (e *TaskDefInvalidError) Error() string { return e.Msg }

// TaskDefInUseError is TaskDefinitionInUseError (a 409): triggers run the definition.
type TaskDefInUseError struct {
	Triggers int64
	What     string
}

func (e *TaskDefInUseError) Error() string {
	return fmt.Sprintf("%d trigger(s) run this saved task; point them elsewhere before you %s", e.Triggers, e.What)
}

// TaskDefCreate is TaskDefinitionCreate after validation; Parameters is the stored JSON.
type TaskDefCreate struct {
	Name        string
	Description string
	AgentID     uuid.UUID
	Parameters  []byte
}

// TaskDefPatch is TaskDefinitionUpdate: nil fields stay.
type TaskDefPatch struct {
	Name        *string
	Description *string
	AgentID     *uuid.UUID
	Parameters  []byte
}

func taskDefStore() store.TaskDefs { return store.TaskDefs{} }

func (x *TaskDefs) get(ctx context.Context, ws scope.Workspace, id uuid.UUID) (store.TaskDefRow, error) {
	var row store.TaskDefRow
	var found bool
	if err := x.s.read(ctx, ws, func(sess db.Session) error {
		var err error
		row, found, err = taskDefStore().Get(ctx, sess, id)
		return err
	}); err != nil {
		return store.TaskDefRow{}, err
	}
	if !found {
		return store.TaskDefRow{}, &TaskDefNotFoundError{ID: id}
	}
	return row, nil
}

// requireAgent is _require_agent.
func (x *TaskDefs) requireAgent(ctx context.Context, sess db.Session, agent uuid.UUID) error {
	status, found, err := taskDefStore().AgentStatus(ctx, sess, agent)
	switch {
	case err != nil:
		return err
	case !found:
		return &TaskDefInvalidError{Msg: fmt.Sprintf("Agent %s does not exist in this workspace", agent)}
	case status == domain.StatusArchived:
		return &TaskDefInvalidError{Msg: fmt.Sprintf("Agent %s is archived; restore it first", agent)}
	}
	return nil
}

// requireUnused is _require_unused.
func (x *TaskDefs) requireUnused(ctx context.Context, ws scope.Workspace, id uuid.UUID, what string) error {
	if x.p.Triggers == nil {
		return &UnwiredError{Feature: "counting the triggers that run a saved task"}
	}
	n, err := x.p.Triggers.CountByTaskDefinition(ctx, ws, id.String())
	if err != nil {
		return err
	}
	if n > 0 {
		return &TaskDefInUseError{Triggers: n, What: what}
	}
	return nil
}

// List is list(agent_id, limit), newest first.
func (x *TaskDefs) List(ctx context.Context, c authn.Caller, agent *uuid.UUID, limit int32) ([]store.TaskDefRow, error) {
	var rows []store.TaskDefRow
	err := x.s.read(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		rows, err = taskDefStore().List(ctx, sess, agent, limit)
		return err
	})
	return rows, err
}

// Create is create: the agent checked, the row and its owner grant written, audited.
func (x *TaskDefs) Create(ctx context.Context, c authn.Caller, in TaskDefCreate) (store.TaskDefRow, error) {
	id := uuid.New()
	if err := x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		if err := x.requireAgent(ctx, sess, in.AgentID); err != nil {
			return err
		}
		row := store.TaskDefRow{ID: id, Name: in.Name, Description: in.Description, AgentID: in.AgentID, Parameters: in.Parameters}
		if err := taskDefStore().Insert(ctx, sess, c.UserID, row, x.s.d.Now()); err != nil {
			return err
		}
		if err := authz.GrantResourceOwner(ctx, x.s.d.Graph, id.String(), c.Workspace.ID(), c.GraphSubject(), authz.OwnerRelations()); err != nil {
			return err
		}
		x.s.Audit(ctx, sess, c, "task_definition.create", "task_definition", id.String())
		return nil
	}); err != nil {
		return store.TaskDefRow{}, err
	}
	return x.get(ctx, c.Workspace, id)
}

// Get is get.
func (x *TaskDefs) Get(ctx context.Context, c authn.Caller, id uuid.UUID) (store.TaskDefRow, error) {
	return x.get(ctx, c.Workspace, id)
}

// Update is update: only non-null fields change; a new agent is checked and
// refused while triggers run the definition.
func (x *TaskDefs) Update(ctx context.Context, c authn.Caller, id uuid.UUID, p TaskDefPatch) (store.TaskDefRow, error) {
	current, err := x.get(ctx, c.Workspace, id)
	if err != nil {
		return store.TaskDefRow{}, err
	}
	if p.AgentID != nil && *p.AgentID == current.AgentID {
		p.AgentID = nil
	}
	if p.AgentID != nil {
		if err := x.s.read(ctx, c.Workspace, func(sess db.Session) error { return x.requireAgent(ctx, sess, *p.AgentID) }); err != nil {
			return store.TaskDefRow{}, err
		}
		if err := x.requireUnused(ctx, c.Workspace, id, "change its agent"); err != nil {
			return store.TaskDefRow{}, err
		}
	}
	if p.Name == nil && p.Description == nil && p.AgentID == nil && p.Parameters == nil {
		return x.audited(ctx, c, "task_definition.update", id, func() (store.TaskDefRow, error) { return x.get(ctx, c.Workspace, id) })
	}
	return x.audited(ctx, c, "task_definition.update", id, func() (store.TaskDefRow, error) {
		var found bool
		if err := x.s.write(ctx, c.Workspace, func(sess db.Session) error {
			row, ok, err := taskDefStore().Get(ctx, sess, id)
			found = ok
			if err != nil || !ok {
				return err
			}
			if p.Name != nil {
				row.Name = *p.Name
			}
			if p.Description != nil {
				row.Description = *p.Description
			}
			if p.AgentID != nil {
				row.AgentID = *p.AgentID
			}
			if p.Parameters != nil {
				row.Parameters = p.Parameters
			}
			return taskDefStore().Update(ctx, sess, row, x.s.d.Now())
		}); err != nil {
			return store.TaskDefRow{}, err
		}
		if !found {
			return store.TaskDefRow{}, &TaskDefNotFoundError{ID: id}
		}
		return x.get(ctx, c.Workspace, id)
	})
}

// audited is @audited around an update: the event is written once fn succeeds.
func (x *TaskDefs) audited(ctx context.Context, c authn.Caller, action string, id uuid.UUID, fn func() (store.TaskDefRow, error)) (store.TaskDefRow, error) {
	row, err := fn()
	if err != nil {
		return store.TaskDefRow{}, err
	}
	x.record(ctx, c, action, id)
	return row, nil
}

func (x *TaskDefs) record(ctx context.Context, c authn.Caller, action string, id uuid.UUID) {
	if x.s.d.Audit == nil {
		return
	}
	if err := x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		x.s.Audit(ctx, sess, c, action, "task_definition", id.String())
		return nil
	}); err != nil && x.s.d.Log != nil {
		x.s.d.Log.WarnContext(ctx, "Failed to record audit event", "action", action, "resource_type", "task_definition", "error", err.Error())
	}
}

// Delete is delete: refused while triggers run the definition; false when there was none.
func (x *TaskDefs) Delete(ctx context.Context, c authn.Caller, id uuid.UUID) (bool, error) {
	if err := x.requireUnused(ctx, c.Workspace, id, "delete it"); err != nil {
		return false, err
	}
	var deleted bool
	if err := x.s.write(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		if deleted, err = taskDefStore().Delete(ctx, sess, id); err != nil || !deleted {
			return err
		}
		x.s.Audit(ctx, sess, c, "task_definition.delete", "task_definition", id.String())
		return nil
	}); err != nil {
		return false, err
	}
	if !deleted {
		return false, nil
	}
	if rw, ok := x.s.d.Graph.(authz.ReadWriter); ok {
		if err := authz.RevokeResource(ctx, rw, id.String()); err != nil && x.s.d.Log != nil {
			x.s.d.Log.WarnContext(ctx, "Deleted TaskDefinitionORM but could not remove its graph tuples", "task_definition_id", id.String(), "error", err.Error())
		}
	}
	return true, nil
}

// Run is run: the definition, the caller's execute on its agent, then the run.
func (x *TaskDefs) Run(ctx context.Context, c authn.Caller, id uuid.UUID, parameters wirejson.Object, createdVia string) (any, error) {
	def, err := x.get(ctx, c.Workspace, id)
	if err != nil {
		return nil, err
	}
	if err := x.s.Require(ctx, c, "execute", def.AgentID); err != nil {
		return nil, err
	}
	if x.p.Runner == nil {
		return nil, &UnwiredError{Feature: "running a saved task"}
	}
	merged := wirejson.Object{}
	if len(def.Parameters) > 0 {
		v, err := wirejson.Unmarshal(def.Parameters)
		if err != nil {
			return nil, err
		}
		if o, ok := v.(wirejson.Object); ok {
			merged = append(merged, o...)
		}
	}
	for _, m := range parameters {
		merged.Set(m.Key, m.Value)
	}
	return x.p.Runner.Start(ctx, c, TaskDefRun{
		DefinitionID: id.String(), AgentID: def.AgentID.String(), Description: def.Description, Parameters: merged, CreatedVia: createdVia,
	})
}
