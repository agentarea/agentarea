package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
)

type agentsLookup struct{ l agentsapi.Lookup }

// AgentsFrom resolves agents through the agents module's lookup.
func AgentsFrom(l agentsapi.Lookup) Agents { return agentsLookup{l} }

func (a agentsLookup) Resolve(ctx context.Context, ws scope.Workspace, idOrSlug string) (uuid.UUID, bool, error) {
	if id, err := uuid.Parse(idOrSlug); err == nil {
		ok, err := a.l.AgentExists(ctx, ws, id.String())
		return id, ok, err
	}
	raw, found, err := a.l.AgentIDBySlug(ctx, ws, idOrSlug)
	if err != nil || !found {
		return uuid.Nil, false, err
	}
	id, err := uuid.Parse(raw)
	return id, err == nil, err
}
