package service

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
)

var (
	_ api.Budgets     = (*Service)(nil)
	_ api.RunPolicies = (*Service)(nil)
)

// layers are the policy layers GovernancePolicyResolver.resolve reads, with
// their rule ids.
type layers struct {
	docs []*api.Policy
	ids  []string
}

func (sv *Service) layer(ctx context.Context, s db.Session, l *layers, subjectType, subjectID string) error {
	enabled := true
	rules, err := sv.d.Policies.List(ctx, s, Filter{SubjectType: &subjectType, SubjectID: &subjectID, Enabled: &enabled})
	if err != nil {
		return err
	}
	rules = sv.known(ctx, rules)
	if len(rules) == 0 {
		return nil
	}
	doc, err := domain.RulesToDocument(rules, sv.d.Log)
	if err != nil {
		return err
	}
	l.docs = append(l.docs, &doc)
	for _, r := range rules {
		l.ids = append(l.ids, r.ID)
	}
	return nil
}

func (sv *Service) ruleLayers(ctx context.Context, s db.Session, agentID, userID string) (layers, error) {
	var l layers
	if err := sv.layer(ctx, s, &l, "workspace", s.Workspace().ID()); err != nil {
		return l, err
	}
	if agentID != "" {
		if err := sv.layer(ctx, s, &l, "agent", agentID); err != nil {
			return l, err
		}
	}
	if userID != "" {
		if err := sv.layer(ctx, s, &l, "user", userID); err != nil {
			return l, err
		}
	}
	return l, nil
}

// resolve is GovernancePolicyResolver.resolve: the workspace, agent and user
// rule layers, then taskPolicy, which may name no approver the rest does not admit.
func (sv *Service) resolve(ctx context.Context, s db.Session, agentID, userID string, taskPolicy *api.Policy) (api.Policy, error) {
	l, err := sv.ruleLayers(ctx, s, agentID, userID)
	if err != nil {
		return api.Policy{}, err
	}
	if taskPolicy != nil {
		ceiling, err := domain.Resolve(l.docs, nil)
		if err != nil {
			return api.Policy{}, err
		}
		if err := domain.ValidateCallerApprovers(ceiling, *taskPolicy); err != nil {
			return api.Policy{}, err
		}
		l.docs = append(l.docs, taskPolicy)
	}
	return domain.Resolve(l.docs, l.ids)
}

func (sv *Service) read(ctx context.Context, ws scope.Workspace, fn func(s db.Session) error) error {
	s, done, err := sv.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer done()
	return fn(s)
}

// Resolve resolves the policy a run starts with.
func (sv *Service) Resolve(ctx context.Context, p api.RunPrincipal, taskPolicy *api.Policy) (api.Policy, error) {
	var out api.Policy
	err := sv.read(ctx, p.Workspace, func(s db.Session) (err error) {
		out, err = sv.resolve(ctx, s, p.AgentID, p.UserID, taskPolicy)
		return err
	})
	return out, err
}

// Preview is the effective-policy preview: workspace and agent layers and
// the caller's task policy, no user layer.
func (sv *Service) Preview(ctx context.Context, ws scope.Workspace, agentID string, taskPolicy *api.Policy) (api.Policy, error) {
	return sv.Resolve(ctx, api.RunPrincipal{Workspace: ws, AgentID: agentID}, taskPolicy)
}

// CurrentBudget is the budget the workspace, agent and user layers set now.
func (sv *Service) CurrentBudget(ctx context.Context, p api.RunPrincipal) (*api.Budget, error) {
	pol, err := sv.Resolve(ctx, p, nil)
	if err != nil {
		return nil, err
	}
	return pol.Budget, nil
}

// Delegation is create_task_with_policy's policy half for a delegated task:
// the target agent's own layers with {budget: {run_budget_usd}} and the
// lower of its own and the parent's token and execution limits as task
// policy, complete, and no looser than the parent's effective policy (whose
// agent cap bounds only the parent's agent). p.UserID is who started the parent run.
func (sv *Service) Delegation(ctx context.Context, p api.RunPrincipal, req api.DelegationRequest) (api.Policy, api.Snapshot, error) {
	run := req.RunBudget
	if run.Sign() <= 0 {
		return api.Policy{}, api.Snapshot{}, errors.New("run_budget_usd: Input should be greater than 0")
	}
	if req.TargetAgentID == "" {
		return api.Policy{}, api.Snapshot{}, errors.New("delegation names no target agent")
	}
	var taskPolicy, effective, ceilings api.Policy
	err := sv.read(ctx, p.Workspace, func(s db.Session) error {
		if err := req.UpperBound.RequireRuntimeContract(); err != nil {
			return err
		}
		var err error
		if ceilings, err = sv.resolve(ctx, s, req.TargetAgentID, p.UserID, nil); err != nil {
			return err
		}
		taskPolicy = domain.LowerLimits(ceilings, req.UpperBound)
		taskPolicy.Budget = &api.Budget{RunBudgetUSD: &run}
		if effective, err = sv.resolve(ctx, s, req.TargetAgentID, p.UserID, &taskPolicy); err != nil {
			return err
		}
		if err := effective.RequireRuntimeContract(); err != nil {
			return err
		}
		upper := req.UpperBound.Document()
		if upper.Budget != nil {
			b := *upper.Budget
			b.AgentMonthlySpendCapUSD = nil
			upper.Budget = &b
		}
		mine := effective.Document()
		_, err = domain.Resolve([]*api.Policy{&upper, &mine}, nil)
		return err
	})
	if err != nil {
		return api.Policy{}, api.Snapshot{}, err
	}
	return effective, api.Snapshot{
		RequestedPolicy:   taskPolicy,
		ResolvedExecution: effective.Execution,
		EffectivePolicy:   effective,
		LimitCeilings:     domain.LimitCeilings(ceilings),
		ResolvedAt:        sv.d.Now(),
		Revision:          1,
	}, nil
}

// ErrSnapshotNotFound is a task without a stored effective policy.
var ErrSnapshotNotFound = errors.New("Task policy snapshot not found") //nolint:staticcheck // Python's detail

// TaskSnapshot is the effective policy stored on the task before dispatch.
func (sv *Service) TaskSnapshot(ctx context.Context, ws scope.Workspace, taskID string) (api.Policy, error) {
	raw, found, err := sv.d.Tasks.TaskMetadata(ctx, ws, taskID)
	if err != nil {
		return api.Policy{}, err
	}
	if !found || len(raw) == 0 {
		return api.Policy{}, ErrSnapshotNotFound
	}
	meta, err := wirejson.Unmarshal(raw)
	if err != nil {
		return api.Policy{}, err
	}
	snap, _ := api.Field(meta, "governance_snapshot")
	eff, _ := api.Field(snap, "effective_policy")
	if !api.IsObject(eff) {
		return api.Policy{}, ErrSnapshotNotFound
	}
	pol, errs := api.ParsePolicy(eff, nil, true)
	if len(errs) > 0 {
		return api.Policy{}, errors.New("stored effective policy does not validate: " + errs[0].Msg)
	}
	return pol, nil
}
