package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// RunnerClient is a client as its runner's socket reads it.
type RunnerClient struct {
	ID          string
	WorkspaceID string
	Kind        string
	// Runner: Kind is one a runner serves (RUNNER_KINDS).
	Runner       bool
	DefaultModel string
	AllowDomains []string
	Sandbox      bool
}

// RunnerModel is one model a runner's CLI reported on hello.
type RunnerModel struct {
	Name             string   `json:"name"`
	ReasoningLevels  []string `json:"reasoning_levels"`
	DefaultReasoning *string  `json:"default_reasoning"`
}

// RunnerAgent is what a runner's turn takes from its agent: the reasoning
// level and the instructions (the agent's instruction, then each skill's SKILL.md).
type RunnerAgent struct {
	ReasoningEffort string
	Instructions    string
}

// RunnerClients is what the runs module's runner socket reads and writes of clients.
type RunnerClients interface {
	// Client is the workspace's client, false when it has none.
	Client(ctx context.Context, ws scope.Workspace, clientID string) (RunnerClient, bool, error)
	// RecordHello stores the models when models is not nil, and defaultModel
	// when it is set and the client has none.
	RecordHello(ctx context.Context, ws scope.Workspace, clientID string, models []RunnerModel, defaultModel string) error
	// Agent returns ErrNotFound when the workspace has no such agent.
	Agent(ctx context.Context, ws scope.Workspace, agentID string) (RunnerAgent, error)
}
