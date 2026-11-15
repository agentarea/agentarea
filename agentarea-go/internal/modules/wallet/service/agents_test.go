package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
)

type lookup struct {
	agentsapi.Lookup
	exists map[string]bool
	slugs  map[string]string
}

func (l *lookup) AgentExists(_ context.Context, _ scope.Workspace, id string) (bool, error) {
	return l.exists[id], nil
}

func (l *lookup) AgentIDBySlug(_ context.Context, _ scope.Workspace, slug string) (string, bool, error) {
	id, ok := l.slugs[slug]
	return id, ok, nil
}
