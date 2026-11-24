package api

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// AgentSummary is one entry of agents_list.
type AgentSummary struct {
	ID          string
	Name        string
	Description *string
}

// AgentDetail is agents_get's output.
type AgentDetail struct {
	ID                 string
	Name               string
	Description        *string
	ModelID            *string
	Instruction        *string
	AgentType          string
	ReasoningEffort    *string
	ReasoningMaxTokens *int
}

// AgentRef is agents_create's and agents_update's output.
type AgentRef struct {
	ID   string
	Name string
}

// Agents is what the platform MCP agents toolset (tools/agents_toolset.py)
// calls. The tool layer checks the relations @requires names; these methods
// check them again, as the REST routes do. A refusal of the input is an
// error whose text is what the toolset reports.
type Agents interface {
	// List is the page [offset, offset+limit) of the agents the caller may
	// read, archived and harness agents left out (AgentService.list() plus
	// readable_resource_ids).
	List(ctx context.Context, c authn.Caller, limit, offset int) ([]AgentSummary, error)
	// Get returns ErrNotFound for an id the workspace has no agent for.
	Get(ctx context.Context, c authn.Caller, agentID string) (AgentDetail, error)
	// Create takes an AgentCreate document as POST /agents/ does.
	Create(ctx context.Context, c authn.Caller, agentCreate json.RawMessage) (AgentRef, error)
	// Update takes an AgentUpdate document (the keys the tool was given).
	Update(ctx context.Context, c authn.Caller, agentID string, agentUpdate json.RawMessage) (AgentRef, error)
	// Archive and Restore are idempotent; ErrNotFound for an unknown agent.
	Archive(ctx context.Context, c authn.Caller, agentID string) error
	Restore(ctx context.Context, c authn.Caller, agentID string) error
}

// Page is items[offset : offset+limit], empty past the end; a negative
// bound counts as zero.
func Page[T any](items []T, limit, offset int) []T {
	offset = min(max(offset, 0), len(items))
	return items[offset:min(offset+max(limit, 0), len(items))]
}
