package app

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	agentsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// lateAgentTriggers is streams' trigger creation, resolved when agents first asks, since streams is built after agents.
type lateAgentTriggers struct{ m *moduleSet }

var _ agentsservice.AgentTriggers = lateAgentTriggers{}

func (t lateAgentTriggers) Check(ctx context.Context, c authn.Caller, specs []json.RawMessage) error {
	return t.m.streams.AgentTriggers().Check(ctx, c, specs)
}

func (t lateAgentTriggers) Create(ctx context.Context, c authn.Caller, agentID string, specs []json.RawMessage) error {
	return t.m.streams.AgentTriggers().Create(ctx, c, agentID, specs)
}
