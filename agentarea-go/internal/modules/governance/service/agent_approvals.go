package service

import (
	"context"
	"errors"
	"slices"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
)

func (sv *Service) agentApprovalRules(ctx context.Context, s db.Session, agentID string, enabledOnly bool) ([]domain.Rule, error) {
	st, effect := "agent", "approval"
	f := Filter{SubjectType: &st, SubjectID: &agentID, Effect: &effect}
	if enabledOnly {
		yes := true
		f.Enabled = &yes
	}
	return sv.d.Policies.List(ctx, s, f)
}

func managedBy(r domain.Rule, by string) bool { return r.ManagedBy != nil && *r.ManagedBy == by }

// SyncAgentApprovals is sync_agent_approval_rules: the agent's toggle-owned
// approval rules become exactly targets; a rule written elsewhere is never
// touched, and a target it already requires gets no second rule.
func (sv *Service) SyncAgentApprovals(ctx context.Context, s db.Session, c authn.Caller, agentID string, targets []string) error {
	existing, err := sv.agentApprovalRules(ctx, s, agentID, false)
	if err != nil {
		return err
	}
	owned := map[string]domain.Rule{}
	authored := map[string]bool{}
	for _, r := range existing {
		switch {
		case managedBy(r, domain.ManagedByAgentTools):
			owned[r.Target] = r
		case r.ManagedBy == nil && r.Enabled:
			authored[r.Target] = true
		}
	}
	now := sv.d.Now()
	for _, t := range targets {
		r, ok := owned[t]
		switch {
		case !ok && authored[t]:
		case !ok:
			by := domain.ManagedByAgentTools
			if _, err := sv.d.Policies.Create(ctx, s, uuid.New(), c.UserID, domain.Rule{
				SubjectType: "agent", SubjectID: agentID, Target: t, Effect: "approval", Params: map[string]any{},
				Enabled: true, ManagedBy: &by,
			}, now); err != nil {
				return err
			}
		case !r.Enabled:
			yes := true
			if _, _, err := sv.d.Policies.Update(ctx, s, uuid.MustParse(r.ID), RulePatch{Enabled: &yes}, now); err != nil {
				return err
			}
		}
	}
	for t, r := range owned {
		if slices.Contains(targets, t) {
			continue
		}
		if _, err := sv.d.Policies.Delete(ctx, s, uuid.MustParse(r.ID)); err != nil {
			return err
		}
	}
	return nil
}

// ReleaseAgentApprovals is release_unticked_approvals in the agent write's
// transaction s; admin is the workspace-admin check of the caller in ctx.
func (sv *Service) ReleaseAgentApprovals(ctx context.Context, s db.Session, agentID string, unticked []string, admin func(context.Context) error) error {
	rules, err := sv.agentApprovalRules(ctx, s, agentID, true)
	if err != nil {
		return err
	}
	var conflicts []domain.Rule
	for _, r := range rules {
		if r.ManagedBy == nil && slices.Contains(unticked, r.Target) {
			conflicts = append(conflicts, r)
		}
	}
	if len(conflicts) == 0 {
		return nil
	}
	err = authz.ErrNotWorkspaceAdmin
	if admin != nil {
		err = admin(ctx)
	}
	if err != nil {
		if !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
			return err
		}
		var targets []string
		for _, r := range conflicts {
			if !slices.Contains(targets, r.Target) {
				targets = append(targets, r.Target)
			}
		}
		slices.Sort(targets)
		return &api.ApprovalEnforcedError{Targets: targets}
	}
	for _, r := range conflicts {
		if _, err := sv.d.Policies.Delete(ctx, s, uuid.MustParse(r.ID)); err != nil {
			return err
		}
	}
	return nil
}

// RequireInstallAllowed is CatalogInstallGuard.require_allowed.
func (sv *Service) RequireInstallAllowed(ctx context.Context, c authn.Caller, registryID, trust string) error {
	var rules []domain.Rule
	err := sv.read(ctx, c.Workspace, func(s db.Session) error {
		yes := true
		for _, layer := range [][2]string{{"workspace", c.Workspace.ID()}, {"user", c.UserID}} {
			got, err := sv.d.Policies.List(ctx, s, Filter{SubjectType: &layer[0], SubjectID: &layer[1], Enabled: &yes})
			if err != nil {
				return err
			}
			rules = append(rules, got...)
		}
		return nil
	})
	if err != nil {
		return err
	}
	if d := domain.DecideCatalogInstall(rules, registryID, trust); !d.Allowed {
		return &api.InstallRefusedError{Reason: d.Reason}
	}
	return nil
}

// RunRefusal is decide_catalog_install over run_time_install_rules (the workspace's alone).
func (sv *Service) RunRefusal(ctx context.Context, ws scope.Workspace, registryID, trust string) (string, bool, error) {
	var rules []domain.Rule
	err := sv.read(ctx, ws, func(s db.Session) error {
		st, sid, yes := "workspace", ws.ID(), true
		var err error
		rules, err = sv.d.Policies.List(ctx, s, Filter{SubjectType: &st, SubjectID: &sid, Enabled: &yes})
		return err
	})
	if err != nil {
		return "", false, err
	}
	d := domain.DecideCatalogInstall(rules, registryID, trust)
	return d.Reason, !d.Allowed, nil
}
