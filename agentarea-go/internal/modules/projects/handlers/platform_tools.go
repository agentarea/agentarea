package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/service"
)

// PlatformTools is api.PlatformProjects over the service, validating
// documents with the REST bodies' rules.
type PlatformTools struct{ Svc *service.Service }

var _ api.PlatformProjects = PlatformTools{}

// errBadUUID is uuid.UUID(s)'s ValueError.
var errBadUUID = errors.New("badly formed hexadecimal UUID string")

var errCycle = errors.New(domain.CycleDetail) //nolint:staticcheck // Python's message

func toolUUID(s string) (uuid.UUID, error) {
	id, err := uuid.Parse(s)
	if err != nil {
		return uuid.Nil, errBadUUID
	}
	return id, nil
}

func toolError(err error) error {
	switch {
	case errors.Is(err, domain.ErrProjectNotFound):
		return api.ErrProjectNotFound
	case errors.Is(err, domain.ErrCycle):
		return errCycle
	}
	return err
}

func platformProject(p domain.Project) api.PlatformProject {
	return api.PlatformProject{ID: p.ID, Name: p.Name, Description: p.Description, Instructions: p.Instructions, ParentProjectID: p.ParentProjectID}
}

func validated(model string, doc json.RawMessage, check func(v any, in *input, errs *[]httpx.FieldError) any) (input, error) {
	v, err := wirejson.Unmarshal(doc)
	if err != nil {
		return input{}, err
	}
	var in input
	var errs []httpx.FieldError
	check(v, &in, &errs)
	if len(errs) > 0 {
		return input{}, &httpx.ModelValidationError{Model: model, Errors: errs}
	}
	return in, nil
}

func (t PlatformTools) List(ctx context.Context, c authn.Caller, limit, offset int) ([]api.PlatformProject, error) {
	if limit < 0 || limit > math.MaxInt32 || offset < 0 || offset > math.MaxInt32 {
		return nil, fmt.Errorf("limit and offset must be between 0 and %d, got %d and %d", math.MaxInt32, limit, offset)
	}
	ps, err := t.Svc.List(ctx, c.Workspace, int32(limit), int32(offset)) //nolint:gosec // bounded above
	if err != nil {
		return nil, err
	}
	out := make([]api.PlatformProject, len(ps))
	for i, p := range ps {
		out[i] = platformProject(p)
	}
	return out, nil
}

func (t PlatformTools) Get(ctx context.Context, c authn.Caller, projectID string) (api.PlatformProject, error) {
	id, err := toolUUID(projectID)
	if err != nil {
		return api.PlatformProject{}, err
	}
	p, err := t.Svc.Get(ctx, c.Workspace, id)
	if err != nil {
		return api.PlatformProject{}, toolError(err)
	}
	return platformProject(p), nil
}

func (t PlatformTools) Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (api.PlatformProject, error) {
	in, err := validated("ProjectCreate", doc, createBody)
	if err != nil {
		return api.PlatformProject{}, err
	}
	p, err := t.Svc.Create(ctx, c.Workspace, c.UserID, in.create)
	if err != nil {
		return api.PlatformProject{}, toolError(err)
	}
	return platformProject(p), nil
}

func (t PlatformTools) Update(ctx context.Context, c authn.Caller, projectID string, doc json.RawMessage) (api.PlatformProject, error) {
	in, err := validated("ProjectUpdate", doc, updateBody)
	if err != nil {
		return api.PlatformProject{}, err
	}
	id, err := toolUUID(projectID)
	if err != nil {
		return api.PlatformProject{}, err
	}
	p, err := t.Svc.Update(ctx, c.Workspace, id, in.patch)
	if err != nil {
		return api.PlatformProject{}, toolError(err)
	}
	return platformProject(p), nil
}

func (t PlatformTools) Delete(ctx context.Context, c authn.Caller, projectID string) (bool, error) {
	id, err := toolUUID(projectID)
	if err != nil {
		return false, err
	}
	err = t.Svc.Delete(ctx, c.Workspace, id)
	if errors.Is(err, domain.ErrProjectNotFound) {
		return false, nil
	}
	return err == nil, err
}

func linkKind(kind string) (domain.LinkKind, error) {
	switch kind {
	case api.LinkSkill:
		return domain.LinkSkill, nil
	case api.LinkAgent:
		return domain.LinkAgent, nil
	case api.LinkMCPInstance:
		return domain.LinkMCPInstance, nil
	}
	return 0, errors.New("unknown project link kind " + kind)
}

func (t PlatformTools) Link(ctx context.Context, c authn.Caller, kind, projectID, childID string) error {
	k, err := linkKind(kind)
	if err != nil {
		return err
	}
	project, err := toolUUID(projectID)
	if err != nil {
		return err
	}
	if _, err := toolUUID(childID); err != nil {
		return err
	}
	return toolError(t.Svc.Link(ctx, c.Workspace, k, project, childID))
}

func (t PlatformTools) Unlink(ctx context.Context, c authn.Caller, kind, projectID, childID string) error {
	k, err := linkKind(kind)
	if err != nil {
		return err
	}
	project, err := toolUUID(projectID)
	if err != nil {
		return err
	}
	child, err := toolUUID(childID)
	if err != nil {
		return err
	}
	return toolError(t.Svc.Unlink(ctx, c.Workspace, k, project, child))
}
