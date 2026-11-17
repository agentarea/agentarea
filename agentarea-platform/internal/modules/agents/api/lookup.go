package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// Lookup answers whether agents and skills exist in a workspace and what
// they are called, as AgentRepository and SkillRepository read them by id
// (workspace_id equal to the workspace's; archived agents included).
type Lookup interface {
	AgentExists(ctx context.Context, ws scope.Workspace, id string) (bool, error)
	SkillExists(ctx context.Context, ws scope.Workspace, id string) (bool, error)
	// AgentNames maps each id of ids that is an agent of ws to its name.
	AgentNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error)
	// SkillNames maps each id of ids that is a skill of ws to its name.
	SkillNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error)
	// AgentIDBySlug is the id of the agent of ws with slug.
	AgentIDBySlug(ctx context.Context, ws scope.Workspace, slug string) (string, bool, error)
}
