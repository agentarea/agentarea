package handlers

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

// AgentsToolset is api.Agents over the agents service, validating documents
// with the REST bodies' rules.
type AgentsToolset struct{ Svc *service.Service }

var _ api.Agents = AgentsToolset{}

func toolsetNotFound(err error) error {
	if errors.Is(err, domain.ErrAgentNotFound) {
		return api.ErrNotFound
	}
	return err
}

func toolsetDocument(raw json.RawMessage, parse func(v any, in *input, errs *[]httpx.FieldError)) (input, error) {
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return input{}, err
	}
	var in input
	var errs []httpx.FieldError
	parse(v, &in, &errs)
	if err := httpx.Validation(errs...); err != nil {
		return input{}, err
	}
	return in, nil
}

func (t AgentsToolset) List(ctx context.Context, c authn.Caller, limit, offset int) ([]api.AgentSummary, error) {
	vs, err := t.Svc.List(ctx, c)
	if err != nil {
		return nil, err
	}
	vs = api.Page(vs, limit, offset)
	out := make([]api.AgentSummary, len(vs))
	for i, v := range vs {
		out[i] = api.AgentSummary{ID: v.Agent.ID, Name: v.Agent.Name, Description: v.Agent.Description}
	}
	return out, nil
}

func (t AgentsToolset) Get(ctx context.Context, c authn.Caller, agentID string) (api.AgentDetail, error) {
	if _, err := uuid.Parse(agentID); err != nil {
		return api.AgentDetail{}, err
	}
	v, err := t.Svc.Get(ctx, c, agentID)
	if err != nil {
		return api.AgentDetail{}, toolsetNotFound(err)
	}
	a := v.Agent
	d := api.AgentDetail{ID: a.ID, Name: a.Name, Description: a.Description, ModelID: a.ModelID,
		Instruction: a.Instruction, AgentType: a.AgentType, ReasoningEffort: a.ReasoningEffort}
	if a.ReasoningMaxTokens != nil {
		n := int(*a.ReasoningMaxTokens)
		d.ReasoningMaxTokens = &n
	}
	return d, nil
}

func (t AgentsToolset) Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (api.AgentRef, error) {
	in, err := toolsetDocument(doc, createBody)
	if err != nil {
		return api.AgentRef{}, err
	}
	v, err := t.Svc.Create(ctx, c, in.create)
	if err != nil {
		return api.AgentRef{}, err
	}
	return api.AgentRef{ID: v.Agent.ID, Name: v.Agent.Name}, nil
}

func (t AgentsToolset) Update(ctx context.Context, c authn.Caller, agentID string, doc json.RawMessage) (api.AgentRef, error) {
	if _, err := uuid.Parse(agentID); err != nil {
		return api.AgentRef{}, err
	}
	in, err := toolsetDocument(doc, updateBody)
	if err != nil {
		return api.AgentRef{}, err
	}
	v, err := t.Svc.Update(ctx, c, agentID, in.patch)
	if err != nil {
		return api.AgentRef{}, toolsetNotFound(err)
	}
	return api.AgentRef{ID: v.Agent.ID, Name: v.Agent.Name}, nil
}

func (t AgentsToolset) Archive(ctx context.Context, c authn.Caller, agentID string) error {
	if _, err := uuid.Parse(agentID); err != nil {
		return err
	}
	return toolsetNotFound(t.Svc.Archive(ctx, c, agentID))
}

func (t AgentsToolset) Restore(ctx context.Context, c authn.Caller, agentID string) error {
	if _, err := uuid.Parse(agentID); err != nil {
		return err
	}
	_, err := t.Svc.Restore(ctx, c, agentID)
	return toolsetNotFound(err)
}
