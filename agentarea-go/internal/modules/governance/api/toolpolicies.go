package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// WorkspaceRule is one enabled workspace-subject rule as a connection's
// Tools page reads it (_tool_policies._default_verdict).
type WorkspaceRule struct {
	Target       string
	Effect       string
	HasCondition bool
	// NamesApprovers: an approval rule whose params name its approvers.
	NamesApprovers bool
}

// ToolPolicies is what connections reads of the policy layers.
type ToolPolicies interface {
	// Workspace is workspace_tool_policy: the workspace's enabled rules and
	// its resolved layer; ErrPolicyRefused when the layer does not validate.
	Workspace(ctx context.Context, c authn.Caller) ([]WorkspaceRule, Policy, error)
	// Effective is the workspace and user layers resolved, which a direct
	// tool call through a connection is judged by.
	Effective(ctx context.Context, ws scope.Workspace, userID string) (Policy, error)
}

// ApprovalTargets reads agents' approval rules (approval_targets_for_agents).
type ApprovalTargets interface {
	// Targets are the targets of the enabled approval rules of each of
	// agentIDs that has any.
	Targets(ctx context.Context, ws scope.Workspace, agentIDs []string) (map[string][]string, error)
}
