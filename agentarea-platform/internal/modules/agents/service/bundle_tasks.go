package service

import (
	"context"
	"encoding/json"
	"errors"
	"math"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// BundleTasks is what a bundle deploy reads and writes of saved tasks.
type BundleTasks struct{ X *TaskDefs }

var _ catalogapi.BundleTasks = BundleTasks{}

func taskRefusal(err error) error {
	var invalid *TaskDefInvalidError
	var inUse *TaskDefInUseError
	switch {
	case errors.As(err, &invalid):
		return &catalogapi.BundleRefusal{Msg: invalid.Msg}
	case errors.As(err, &inUse):
		return &catalogapi.BundleRefusal{Msg: inUse.Error()}
	}
	return err
}

func taskParameters(p map[string]any) ([]byte, error) {
	if p == nil {
		p = map[string]any{}
	}
	return json.Marshal(p)
}

func (b BundleTasks) TaskName(ctx context.Context, c authn.Caller, id string) (string, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return "", false, nil
	}
	row, err := b.X.Get(ctx, c, u)
	var nf *TaskDefNotFoundError
	switch {
	case errors.As(err, &nf):
		return "", false, nil
	case err != nil:
		return "", false, err
	}
	return row.Name, true, nil
}

func (b BundleTasks) CreateTask(ctx context.Context, c authn.Caller, spec catalogapi.BundleTaskSpec) (string, error) {
	agent, err := uuid.Parse(spec.AgentID)
	if err != nil {
		return "", &catalogapi.BundleRefusal{Msg: "agent " + spec.AgentID + " is not an agent id"}
	}
	params, err := taskParameters(spec.Parameters)
	if err != nil {
		return "", err
	}
	row, err := b.X.Create(ctx, c, TaskDefCreate{Name: spec.Name, Description: spec.Prompt, AgentID: agent, Parameters: params})
	if err != nil {
		return "", taskRefusal(err)
	}
	return row.ID.String(), nil
}

// UpdateTask is the edit route's update: the caller edits the saved task.
func (b BundleTasks) UpdateTask(ctx context.Context, c authn.Caller, id string, spec catalogapi.BundleTaskSpec) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return catalogapi.ErrBundleEntityGone
	}
	agent, err := uuid.Parse(spec.AgentID)
	if err != nil {
		return &catalogapi.BundleRefusal{Msg: "agent " + spec.AgentID + " is not an agent id"}
	}
	if err := b.X.s.Require(ctx, c, "edit", u); errors.Is(err, ErrDenied) {
		return &catalogapi.BundleRefusal{Msg: "you may not edit task definition " + id}
	} else if err != nil {
		return err
	}
	params, err := taskParameters(spec.Parameters)
	if err != nil {
		return err
	}
	_, err = b.X.Update(ctx, c, u, TaskDefPatch{Name: &spec.Name, Description: &spec.Prompt, AgentID: &agent, Parameters: params})
	var nf *TaskDefNotFoundError
	if errors.As(err, &nf) {
		return catalogapi.ErrBundleEntityGone
	}
	return taskRefusal(err)
}

func (b BundleTasks) DeleteTask(ctx context.Context, c authn.Caller, id string) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	_, err = b.X.Delete(ctx, c, u)
	return err
}

func (b BundleTasks) TaskNamed(ctx context.Context, c authn.Caller, name string) ([]catalogapi.BundleTaskRef, error) {
	rows, err := b.X.List(ctx, c, nil, math.MaxInt32)
	if err != nil {
		return nil, err
	}
	var out []catalogapi.BundleTaskRef
	for _, r := range rows {
		if r.Name == name {
			out = append(out, catalogapi.BundleTaskRef{ID: r.ID.String(), AgentID: r.AgentID.String()})
		}
	}
	return out, nil
}
