package handlers

import (
	"context"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/governance"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// preview is EffectivePolicyPreviewRequest.
type preview struct {
	agentID    string
	taskPolicy *api.Policy
}

func previewBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	if x, present := o.Get("agent_id"); present && x != nil {
		s, isStr := x.(string)
		if !isStr {
			*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: body("agent_id"), Msg: "UUID input should be a string, bytes or UUID object"})
		} else if id, fe := httpx.ValidateUUID(s, "body", "agent_id"); fe != nil {
			*errs = append(*errs, *fe)
		} else {
			in.agentID = id
		}
	}
	if x, present := o.Get("task_policy"); present && x != nil {
		var c api.Checker
		p := c.Policy(x, body("task_policy"), false)
		*errs = append(*errs, c.Errs...)
		in.taskPolicy = &p
	}
	var c api.Checker
	c.Extra(o, []string{"agent_id", "task_policy"}, body())
	*errs = append(*errs, c.Errs...)
}

func effectiveResponse(p api.Policy) wirejson.Object {
	return wirejson.Object{{Key: "effective_policy", Value: p.EffectiveJSON()}}
}

func (s *Server) PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPost(ctx context.Context, _ gen.PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostRequestObject) (gen.PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	p, err := s.svc.Preview(ctx, c.Workspace, in.agentID, in.taskPolicy)
	if err != nil {
		return nil, err
	}
	return ok(effectiveResponse(p)), nil
}

func (s *Server) GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGet(ctx context.Context, _ gen.GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetRequestObject) (gen.GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	p, err := s.svc.TaskSnapshot(ctx, c.Workspace, inputFrom(ctx).path["task_id"])
	if err != nil {
		return nil, err
	}
	return ok(effectiveResponse(p)), nil
}
