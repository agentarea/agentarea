package api

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// SkillRef is a skill attached to an agent.
type SkillRef struct {
	ID   string
	Name string
}

// NetworkAgent is a live agent as the network graph draws it. Tools is the
// stored tools JSON, nil when NULL; Skills are its skills of the workspace.
type NetworkAgent struct {
	ID          string
	Name        string
	Status      string
	Description *string
	ModelID     *string
	Tools       json.RawMessage
	Skills      []SkillRef
}

// NetworkSkill is a skill of the workspace with its network scope.
type NetworkSkill struct {
	ID           string
	Name         string
	Description  *string
	SourceType   string
	NetworkScope string
}

// SkillMember is a bundle membership: Child is a member of Parent.
type SkillMember struct {
	ParentID string
	ChildID  string
}

// AgentName is one agent of a workspace, archived ones included.
type AgentName struct {
	ID   string
	Name string
}

// Network is what the network graph, its people access and the dashboard read of agents.
type Network interface {
	// NetworkAgents is the workspace's agents that are not archived.
	NetworkAgents(ctx context.Context, ws scope.Workspace) ([]NetworkAgent, error)
	// NetworkSkills is every skill of the workspace and the bundle memberships among them.
	NetworkSkills(ctx context.Context, ws scope.Workspace) ([]NetworkSkill, []SkillMember, error)
	// AllAgents is every agent of the workspace, archived ones included, by id.
	AllAgents(ctx context.Context, ws scope.Workspace) ([]AgentName, error)
}
