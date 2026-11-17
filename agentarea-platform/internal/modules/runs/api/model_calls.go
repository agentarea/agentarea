package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// ModelCallFor is who a model call outside a run is made for: the user it acts as, the agent
// whose spend caps it falls under, and what the ledger line says it was for.
type ModelCallFor struct {
	UserID, AgentID string
	Purpose         string
	TriggerID       string
}

// ChatOnce is one prompt to a chat model, answered whole.
type ChatOnce struct {
	ModelID     string
	Prompt      string
	MaxTokens   int
	Temperature float64
}

// DecideOnce is one System One request to a decision model.
type DecideOnce struct {
	ModelID   string
	State     any
	Questions map[string]any
}

// ModelCallRefused is billing or a spend cap refusing the call; its words are safe to repeat.
type ModelCallRefused struct{ Msg string }

func (e *ModelCallRefused) Error() string { return e.Msg }

// ModelCallFailed is a call that did not complete; Detail never repeats what the endpoint said.
type ModelCallFailed struct{ Detail string }

func (e *ModelCallFailed) Error() string { return e.Detail }

// OneShotModels makes funded model calls outside a run, each held, charged and written to the
// spend ledger like a run's (fund_model_call, charge_model_call).
type OneShotModels interface {
	Chat(ctx context.Context, ws scope.Workspace, who ModelCallFor, in ChatOnce) (string, error)
	Decide(ctx context.Context, ws scope.Workspace, who ModelCallFor, in DecideOnce) (map[string]map[string]any, error)
}
