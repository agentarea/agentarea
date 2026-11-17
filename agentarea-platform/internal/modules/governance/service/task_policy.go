package service

import (
	"context"
	"encoding/json"
	"math"
	"strconv"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
)

func refusal(msg string) error { return &api.ValidationError{Message: msg} }

// positiveInt is the int that `isinstance(v, int) and not isinstance(v, bool)
// and v > 0` admits; a decoder that reads every number as float64 passes an
// integral one.
func positiveInt(v any) (int64, bool) {
	switch x := v.(type) {
	case int:
		return int64(x), x > 0
	case int64:
		return x, x > 0
	case float64:
		return int64(x), x > 0 && x == math.Trunc(x) && x < math.MaxInt64
	}
	n, ok := v.(json.Number)
	if !ok {
		return 0, false
	}
	i, err := strconv.ParseInt(string(n), 10, 64)
	if err != nil {
		if len(n) > 0 && n[0] != '-' {
			return math.MaxInt64, true
		}
		return 0, false
	}
	return i, i > 0
}

// pyEqualsInt is Python's v == n for a JSON value against an int.
func pyEqualsInt(v any, n int64) bool {
	switch x := v.(type) {
	case bool:
		return (x && n == 1) || (!x && n == 0)
	case json.Number:
		if i, err := strconv.ParseInt(string(x), 10, 64); err == nil {
			return i == n
		}
		return false
	case wirejson.Float:
		return float64(x) == float64(n)
	case float64:
		return x == float64(n)
	case int:
		return int64(x) == n
	case int64:
		return x == n
	}
	return false
}

// mergeDocuments is PolicyResolver().resolve([a, b]) read back as a PolicyDocument.
func mergeDocuments(a *api.Policy, b api.Policy) (*api.Policy, error) {
	if a == nil {
		return &b, nil
	}
	m, err := domain.Resolve([]*api.Policy{a, &b}, nil)
	if err != nil {
		return nil, err
	}
	doc := m.Document()
	return &doc, nil
}

// withExecutionLimit is _with_requested_execution_limits for a requested
// max_model_turns that already passed the type check.
func withExecutionLimit(tp *api.Policy, turns int64) (*api.Policy, error) {
	if tp != nil && tp.Execution != nil && tp.Execution.MaxModelTurns != nil && *tp.Execution.MaxModelTurns != turns {
		return nil, refusal("execution.max_model_turns conflicts with task_policy.execution.max_model_turns")
	}
	return mergeDocuments(tp, api.Policy{Execution: &api.Execution{MaxModelTurns: &turns}})
}

// requestedPolicy is start_run's execution merge, then create_task_with_policy's
// max_iterations and approval merges.
func requestedPolicy(req api.TaskRequest) (*api.Policy, error) {
	tp := req.TaskPolicy
	var err error
	if req.ExecutionTurns != nil {
		if req.MaxIterations != nil && !pyEqualsInt(req.MaxIterations, *req.ExecutionTurns) {
			return nil, refusal("execution.max_model_turns conflicts with parameters.max_iterations")
		}
		if tp, err = withExecutionLimit(tp, *req.ExecutionTurns); err != nil {
			return nil, err
		}
	}
	if req.MaxIterations != nil {
		turns, ok := positiveInt(req.MaxIterations)
		if !ok {
			return nil, refusal("parameters.max_iterations must be a positive integer")
		}
		if tp, err = withExecutionLimit(tp, turns); err != nil {
			return nil, err
		}
	}
	if req.RequiresHumanApproval {
		yes := true
		if tp, err = mergeDocuments(tp, api.Policy{Approval: &api.Approval{RequiresHumanApproval: &yes}}); err != nil {
			return nil, err
		}
	}
	return tp, nil
}

// Task is start_run's and create_task_with_policy's policy half: the caller's
// requests merged into its task policy, resolved under the workspace, agent
// and user layers, complete, with the ceilings the layers alone set.
func (sv *Service) Task(ctx context.Context, p api.RunPrincipal, req api.TaskRequest) (api.Policy, api.Snapshot, error) {
	tp, err := requestedPolicy(req)
	if err != nil {
		return api.Policy{}, api.Snapshot{}, err
	}
	var effective, ceilings api.Policy
	err = sv.read(ctx, p.Workspace, func(s db.Session) error {
		var err error
		if effective, err = sv.resolve(ctx, s, p.AgentID, p.UserID, tp); err != nil {
			return err
		}
		if err := effective.RequireRuntimeContract(); err != nil {
			return err
		}
		ceilings, err = sv.resolve(ctx, s, p.AgentID, p.UserID, nil)
		return err
	})
	if err != nil {
		return api.Policy{}, api.Snapshot{}, err
	}
	snap := api.Snapshot{
		ResolvedExecution: effective.Execution,
		EffectivePolicy:   effective,
		LimitCeilings:     domain.LimitCeilings(ceilings),
		ResolvedAt:        sv.d.Now(),
		Revision:          1,
	}
	if tp != nil {
		snap.RequestedPolicy = *tp
		snap.RequestedExecution = tp.Execution
	}
	return effective, snap, nil
}
