package handlers

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// ClientsToolset is api.Clients over the clients service, validating documents
// with the REST bodies' rules and checking the relations the tools' @requires name.
type ClientsToolset struct {
	Svc     *service.Service
	Clients *service.Clients
}

var _ api.Clients = ClientsToolset{}

func (t ClientsToolset) require(ctx context.Context, c authn.Caller, permission, clientID string) (uuid.UUID, error) {
	id, err := uuid.Parse(clientID)
	if err != nil {
		return uuid.Nil, err
	}
	return id, t.Svc.Require(ctx, c, permission, id)
}

func (t ClientsToolset) summary(v service.ClientView) api.ClientSummary {
	return api.ClientSummary{ID: v.ID.String(), Name: v.Name, Kind: v.Kind, MCPEndpointURL: v.EndpointURL}
}

func (t ClientsToolset) List(ctx context.Context, c authn.Caller, limit, offset int) ([]api.ClientSummary, error) {
	vs, err := t.Clients.List(ctx, c, int32(limit), int32(offset))
	if err != nil {
		return nil, err
	}
	out := make([]api.ClientSummary, len(vs))
	for i, v := range vs {
		out[i] = t.summary(v)
	}
	return out, nil
}

func (t ClientsToolset) Get(ctx context.Context, c authn.Caller, clientID string) (json.RawMessage, error) {
	id, err := t.require(ctx, c, "read", clientID)
	if err != nil {
		return nil, err
	}
	v, err := t.Clients.Get(ctx, c, id)
	if errors.Is(err, service.ErrClientNotFound) {
		return nil, api.ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	body, err := clientJSON(v)
	if err != nil {
		return nil, err
	}
	return wirejson.Marshal(body, wirejson.Compact)
}

func (t ClientsToolset) Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (api.ClientSummary, error) {
	in, err := toolsetDocument(doc, clientCreateBody)
	if err != nil {
		return api.ClientSummary{}, err
	}
	ci, _ := in.area.(clientInput)
	v, err := t.Clients.Create(ctx, c, ci.name, ci.description, ci.kind)
	if err != nil {
		return api.ClientSummary{}, err
	}
	return t.summary(v), nil
}

func (t ClientsToolset) Update(ctx context.Context, c authn.Caller, clientID string, doc json.RawMessage) (api.ClientSummary, error) {
	id, err := t.require(ctx, c, "edit", clientID)
	if err != nil {
		return api.ClientSummary{}, err
	}
	in, err := toolsetDocument(doc, clientUpdateBody)
	if err != nil {
		return api.ClientSummary{}, err
	}
	ci, _ := in.area.(clientInput)
	v, err := t.Clients.Update(ctx, c, id, ci.patch)
	if errors.Is(err, service.ErrClientNotFound) {
		return api.ClientSummary{}, api.ErrNotFound
	}
	if err != nil {
		return api.ClientSummary{}, err
	}
	return t.summary(v), nil
}

func (t ClientsToolset) Delete(ctx context.Context, c authn.Caller, clientID string) (bool, error) {
	id, err := t.require(ctx, c, "delete", clientID)
	if err != nil {
		return false, err
	}
	err = t.Clients.Delete(ctx, c, id)
	if errors.Is(err, service.ErrClientNotFound) {
		return false, nil
	}
	return err == nil, err
}

func (t ClientsToolset) AddSkill(ctx context.Context, c authn.Caller, clientID, skillID string) error {
	id, err := t.require(ctx, c, "edit", clientID)
	if err != nil {
		return err
	}
	return t.Clients.AddSkill(ctx, c, id, skillID)
}

func (t ClientsToolset) RemoveSkill(ctx context.Context, c authn.Caller, clientID, skillID string) error {
	id, err := t.require(ctx, c, "edit", clientID)
	if err != nil {
		return err
	}
	skill, err := uuid.Parse(skillID)
	if err != nil {
		return err
	}
	return t.Clients.RemoveSkill(ctx, c, id, skill)
}

func clientToolList(tools []string) *[]string {
	if tools == nil {
		return nil
	}
	return &tools
}

func (t ClientsToolset) AddMCPInstance(ctx context.Context, c authn.Caller, clientID, instanceID string, prefix *string, allowed []string) error {
	id, err := t.require(ctx, c, "edit", clientID)
	if err != nil {
		return err
	}
	return t.Clients.AddMCPInstance(ctx, c, id, instanceID, prefix, clientToolList(allowed))
}

func (t ClientsToolset) RemoveMCPInstance(ctx context.Context, c authn.Caller, clientID, instanceID string) error {
	id, err := t.require(ctx, c, "edit", clientID)
	if err != nil {
		return err
	}
	instance, err := uuid.Parse(instanceID)
	if err != nil {
		return err
	}
	return t.Clients.RemoveMCPInstance(ctx, c, id, instance)
}

func (t ClientsToolset) AddOpenAPIConnection(ctx context.Context, c authn.Caller, clientID, connectionID string, prefix *string, allowed []string) error {
	id, err := t.require(ctx, c, "edit", clientID)
	if err != nil {
		return err
	}
	return t.Clients.AddOpenAPIConnection(ctx, c, id, connectionID, prefix, clientToolList(allowed))
}

func (t ClientsToolset) RemoveOpenAPIConnection(ctx context.Context, c authn.Caller, clientID, connectionID string) error {
	id, err := t.require(ctx, c, "edit", clientID)
	if err != nil {
		return err
	}
	conn, err := uuid.Parse(connectionID)
	if err != nil {
		return err
	}
	return t.Clients.RemoveOpenAPIConnection(ctx, c, id, conn)
}

func (t ClientsToolset) AddPlatformToolset(ctx context.Context, c authn.Caller, clientID, toolset string, disabled []string) (string, error) {
	id, err := t.require(ctx, c, "edit", clientID)
	if err != nil {
		return "", err
	}
	return t.Clients.SetToolset(ctx, c, id, toolset, clientToolList(disabled))
}

func (t ClientsToolset) RemovePlatformToolset(ctx context.Context, c authn.Caller, clientID, toolset string) error {
	id, err := t.require(ctx, c, "edit", clientID)
	if err != nil {
		return err
	}
	return t.Clients.RemoveToolset(ctx, c, id, toolset)
}
