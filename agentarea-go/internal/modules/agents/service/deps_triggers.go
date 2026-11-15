package service

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// AgentTriggers makes the triggers sent with a new agent (streams module,
// agents.py create_agent with _trigger_creation.py).
type AgentTriggers interface {
	// Check is validate_configuration of each TriggerSpec document, before
	// the agent exists; a refusal is an error the HTTP layer renders.
	Check(ctx context.Context, c authn.Caller, specs []json.RawMessage) error
	// Create makes each spec a trigger of agentID in order; when one fails
	// it deletes the ones it made and returns that error.
	Create(ctx context.Context, c authn.Caller, agentID string, specs []json.RawMessage) error
}
