package api

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// AgentTriggers makes the triggers sent with a new agent (agents' AgentTriggers port).
type AgentTriggers interface {
	// Check refuses a bad TriggerSpec document before the agent exists.
	Check(ctx context.Context, c authn.Caller, specs []json.RawMessage) error
	// Create makes each spec a trigger of agentID; on a failure it deletes the ones it made.
	Create(ctx context.Context, c authn.Caller, agentID string, specs []json.RawMessage) error
}
