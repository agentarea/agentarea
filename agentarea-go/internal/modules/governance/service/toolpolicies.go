package service

import (
	"context"
	"slices"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

var _ api.ToolPolicies = (*Service)(nil)

// Workspace is workspace_tool_policy.
func (sv *Service) Workspace(ctx context.Context, c authn.Caller) ([]api.WorkspaceRule, api.Policy, error) {
	var rules []api.WorkspaceRule
	var pol api.Policy
	err := sv.read(ctx, c.Workspace, func(s db.Session) error {
		st, sid, enabled := "workspace", c.Workspace.ID(), true
		rows, err := sv.d.Policies.List(ctx, s, Filter{SubjectType: &st, SubjectID: &sid, Enabled: &enabled})
		if err != nil {
			return err
		}
		for _, r := range rows {
			approvers, _ := api.Field(r.Params, "approvers")
			rules = append(rules, api.WorkspaceRule{
				Target: r.Target, Effect: r.Effect, HasCondition: r.Condition != nil && *r.Condition != "",
				NamesApprovers: api.Truthy(approvers),
			})
		}
		pol, err = sv.resolve(ctx, s, "", "", nil)
		return err
	})
	return rules, pol, err
}

// Effective resolves the workspace and user layers.
func (sv *Service) Effective(ctx context.Context, ws scope.Workspace, userID string) (api.Policy, error) {
	return sv.Resolve(ctx, api.RunPrincipal{Workspace: ws, UserID: userID}, nil)
}

var _ api.ApprovalTargets = (*Service)(nil)

// Targets is approval_targets_for_agents.
func (sv *Service) Targets(ctx context.Context, ws scope.Workspace, agentIDs []string) (map[string][]string, error) {
	wanted := make(map[string]bool, len(agentIDs))
	for _, id := range agentIDs {
		wanted[id] = true
	}
	out := map[string][]string{}
	err := sv.read(ctx, ws, func(s db.Session) error {
		st, effect, enabled := "agent", "approval", true
		rows, err := sv.d.Policies.List(ctx, s, Filter{SubjectType: &st, Effect: &effect, Enabled: &enabled})
		if err != nil {
			return err
		}
		for _, r := range rows {
			if !wanted[r.SubjectID] || slices.Contains(out[r.SubjectID], r.Target) {
				continue
			}
			out[r.SubjectID] = append(out[r.SubjectID], r.Target)
		}
		return nil
	})
	return out, err
}
