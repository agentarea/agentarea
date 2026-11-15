package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
	identityapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
)

// MCPServersToolset is api.PlatformMCPServers over the connections service.
type MCPServersToolset struct {
	Svc   *service.Service
	Slugs identityapi.WorkspaceSlugs
}

var _ api.PlatformMCPServers = MCPServersToolset{}

// slugOf is the caller's workspace slug, read when the caller carries none.
func slugOf(ctx context.Context, slugs identityapi.WorkspaceSlugs, c authn.Caller) func() (string, error) {
	return func() (string, error) {
		if s := c.Workspace.Slug(); s != "" {
			return s, nil
		}
		if slugs == nil {
			return "", errors.New("connections: workspace slugs are not wired")
		}
		return slugs.Slug(ctx, c.Workspace.ID())
	}
}

// validationText is MCPValidationError's text: its errors joined.
func validationText(err error) error {
	var inv *domain.SpecInvalid
	if errors.As(err, &inv) {
		return errors.New(strings.Join(inv.Errors, "; "))
	}
	return err
}

func instanceOut(v service.InstanceView) api.MCPInstance {
	i := v.Instance
	var verification any = i.VerificationRaw
	if v.Verification != nil {
		verification = *v.Verification
	} else if i.VerificationRaw == nil {
		verification = i.Verification
	}
	return api.MCPInstance{
		ID: i.ID, Name: i.Name, Description: i.Description, Verification: verification,
		ServerSpecID: i.ServerSpecID, LastDispatch: i.LastDispatch, Tools: i.Tools,
	}
}

func (t MCPServersToolset) withAction(ctx context.Context, c authn.Caller, v service.InstanceView, probe bool) (api.MCPInstance, error) {
	out := instanceOut(v)
	action, err := t.Svc.InstanceConnectAction(ctx, c, v.Instance, probe, slugOf(ctx, t.Slugs, c))
	if err != nil {
		return api.MCPInstance{}, err
	}
	out.ActionRequired = action
	return out, nil
}

// reread is the instance as stored now, after a write or a probe recorded something.
func (t MCPServersToolset) reread(ctx context.Context, c authn.Caller, id uuid.UUID) (service.InstanceView, error) {
	return t.Svc.InstanceViewOf(ctx, c, id, false)
}

func (t MCPServersToolset) Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (api.MCPInstance, error) {
	o, err := toolDocument(doc)
	if err != nil {
		return api.MCPInstance{}, err
	}
	in, err := checkedInput(o, instanceCreateBody)
	if err != nil {
		return api.MCPInstance{}, err
	}
	v, err := t.Svc.CreateInstance(ctx, c, in.instance.create)
	if err != nil {
		return api.MCPInstance{}, validationText(err)
	}
	return t.withAction(ctx, c, v, true)
}

func (t MCPServersToolset) Update(ctx context.Context, c authn.Caller, instanceID string, doc json.RawMessage) (api.MCPInstance, error) {
	id, err := requireOn(ctx, t.Svc, c, "edit", "mcp_instance", "instance_id", instanceID)
	if err != nil {
		return api.MCPInstance{}, err
	}
	o, err := toolDocument(doc)
	if err != nil {
		return api.MCPInstance{}, err
	}
	if len(o) == 0 {
		return api.MCPInstance{}, errors.New("no fields to update")
	}
	in, err := checkedInput(o, instanceUpdateBody)
	if err != nil {
		return api.MCPInstance{}, err
	}
	v, err := t.Svc.UpdateInstance(ctx, c, id, in.instance.patch)
	if err != nil {
		return api.MCPInstance{}, notFoundAs(validationText(err), api.ErrNotFound)
	}
	return t.withAction(ctx, c, v, true)
}

func (t MCPServersToolset) List(ctx context.Context, c authn.Caller) ([]api.MCPInstance, error) {
	vs, err := t.Svc.ListInstances(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]api.MCPInstance, len(vs))
	for i, v := range vs {
		out[i] = instanceOut(v)
	}
	return out, nil
}

func (t MCPServersToolset) Get(ctx context.Context, c authn.Caller, instanceID string) (api.MCPInstance, error) {
	id, err := uuid.Parse(instanceID)
	if err != nil {
		return api.MCPInstance{}, err
	}
	v, err := t.Svc.InstanceViewOf(ctx, c, id, false)
	if err != nil {
		return api.MCPInstance{}, notFoundAs(err, api.ErrNotFound)
	}
	return t.withAction(ctx, c, v, false)
}

func (t MCPServersToolset) Delete(ctx context.Context, c authn.Caller, instanceID string) (bool, error) {
	id, err := requireOn(ctx, t.Svc, c, "delete", "mcp_instance", "instance_id", instanceID)
	if err != nil {
		return false, err
	}
	err = t.Svc.DeleteInstance(ctx, c, id)
	var nf *domain.NotFound
	if errors.As(err, &nf) {
		return false, nil
	}
	return err == nil, err
}

func (t MCPServersToolset) Verify(ctx context.Context, c authn.Caller, instanceID string) (any, *api.ConnectAction, error) {
	id, err := requireOn(ctx, t.Svc, c, "edit", "mcp_instance", "instance_id", instanceID)
	if err != nil {
		return nil, nil, err
	}
	result, err := t.Svc.Verify(ctx, c.Workspace, id, true)
	if err != nil {
		return nil, nil, err
	}
	v, err := t.reread(ctx, c, id)
	var nf *domain.NotFound
	if errors.As(err, &nf) {
		return result, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	action, err := t.Svc.InstanceConnectAction(ctx, c, v.Instance, true, slugOf(ctx, t.Slugs, c))
	if err != nil || action == nil {
		return result, nil, err
	}
	if v, err = t.reread(ctx, c, id); err != nil {
		return nil, nil, err
	}
	return instanceOut(v).Verification, action, nil
}

func (t MCPServersToolset) GetSpec(ctx context.Context, c authn.Caller, specID string) (api.MCPSpec, error) {
	if _, err := uuid.Parse(specID); err != nil {
		return api.MCPSpec{}, err
	}
	s, ok, err := t.Svc.MCPSpec(ctx, c, specID)
	if err != nil {
		return api.MCPSpec{}, err
	}
	if !ok {
		return api.MCPSpec{}, api.ErrNotFound
	}
	if !s.Catalog {
		if err := t.Svc.Require(ctx, c, "read", "mcp_server", specID); err != nil {
			return api.MCPSpec{}, toolRefusal(err)
		}
	}
	return api.MCPSpec{
		ID: s.ID, Name: s.Name, Description: s.Description, Version: s.Version, Tags: s.Tags,
		IsPublic: s.IsPublic, RemoteURL: s.RemoteURL, DockerImageURL: s.DockerImageURL, Status: s.Status,
		EnvSchema: s.EnvSchema, RegistryURL: s.RegistryURL,
	}, nil
}
