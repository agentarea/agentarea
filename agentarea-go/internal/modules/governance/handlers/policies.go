package handlers

import (
	"context"
	"math"
	"net/url"
	"slices"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/governance"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/service"
)

type ruleList struct{ filter service.Filter }

type ruleCreate struct{ rule domain.Rule }

// rulePatch is PolicyRuleUpdateRequest: sent holds every sent key, nulls
// included (exclude_unset); patch the non-null ones the repository writes.
type rulePatch struct {
	sent  map[string]any
	patch service.RulePatch
}

const (
	priorityMin = math.MinInt32
	priorityMax = math.MaxInt32
)

func ruleFields() []string {
	return []string{"subject_type", "subject_id", "target", "effect", "params", "condition", "enabled", "priority"}
}

func enumQuery(q url.Values, key string, choices []string, errs *[]httpx.FieldError) *string {
	v, ok := last(q, key)
	if !ok {
		return nil
	}
	if !slices.Contains(choices, v) {
		*errs = append(*errs, httpx.EnumError(choices, "query", key))
		return nil
	}
	return &v
}

func ruleListQuery(q url.Values, in *input, errs *[]httpx.FieldError) {
	f := &in.filter
	f.SubjectType = enumQuery(q, "subject_type", domain.SubjectTypes(), errs)
	if v, ok := last(q, "subject_id"); ok {
		f.SubjectID = &v
	}
	f.Effect = enumQuery(q, "effect", domain.Effects(), errs)
	if v, ok := last(q, "target"); ok {
		f.Target = &v
	}
	if v, ok := last(q, "enabled"); ok {
		b, good := httpx.ParseBool(v)
		if !good {
			*errs = append(*errs, httpx.BoolParsing("query", "enabled"))
		} else {
			f.Enabled = &b
		}
	}
}

func enumField(c *api.Checker, v any, loc []any, choices []string) (string, bool) {
	if s, ok := v.(string); ok && slices.Contains(choices, s) {
		return s, true
	}
	c.Errs = append(c.Errs, httpx.EnumError(choices, loc...))
	return "", false
}

func priority(c *api.Checker, v any) (int64, bool) {
	n, ok := c.Int(v, body("priority"), false)
	if !ok {
		return 0, false
	}
	if n < priorityMin {
		c.Errs = append(c.Errs, httpx.GreaterThanEqual(priorityMin, body("priority")...))
		return 0, false
	}
	if n > priorityMax {
		c.Errs = append(c.Errs, httpx.LessThanEqual(priorityMax, body("priority")...))
		return 0, false
	}
	return n, true
}

func dictField(c *api.Checker, v any, loc []any) (any, bool) {
	if !api.IsObject(v) {
		c.Errs = append(c.Errs, httpx.DictType(loc...))
		return nil, false
	}
	return v, true
}

// ruleCreateBody is PolicyRuleCreateRequest (extra="forbid").
func ruleCreateBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var c api.Checker
	r := domain.Rule{Enabled: true, Params: wirejson.Object{}}
	required := func(key string, f func(x any)) {
		x, present := o.Get(key)
		if !present {
			c.Errs = append(c.Errs, httpx.Missing(body(key)...))
			return
		}
		f(x)
	}
	required("subject_type", func(x any) { r.SubjectType, _ = enumField(&c, x, body("subject_type"), domain.SubjectTypes()) })
	required("subject_id", func(x any) { r.SubjectID, _ = c.Str(x, body("subject_id"), 0, 0) })
	required("target", func(x any) { r.Target, _ = c.Str(x, body("target"), 0, 0) })
	required("effect", func(x any) { r.Effect, _ = enumField(&c, x, body("effect"), domain.Effects()) })
	if x, present := o.Get("params"); present {
		if p, ok := dictField(&c, x, body("params")); ok {
			r.Params = p
		}
	}
	if x, present := o.Get("condition"); present {
		r.Condition = c.OptStr(x, true, body("condition"), 0, 0)
	}
	if x, present := o.Get("enabled"); present {
		r.Enabled, _ = c.Bool(x, body("enabled"))
	}
	if x, present := o.Get("priority"); present {
		r.Priority, _ = priority(&c, x)
	}
	c.Extra(o, ruleFields(), body())
	*errs = append(*errs, c.Errs...)
	in.rule = r
}

// ruleUpdateBody is PolicyRuleUpdateRequest: every field optional and nullable.
func ruleUpdateBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var c api.Checker
	in.sent = map[string]any{}
	p := &in.patch
	str := func(key string, choices []string) *string {
		x, present := o.Get(key)
		if !present {
			return nil
		}
		in.sent[key] = nil
		if x == nil {
			return nil
		}
		var s string
		var good bool
		if choices != nil {
			s, good = enumField(&c, x, body(key), choices)
		} else {
			s, good = c.Str(x, body(key), 0, 0)
		}
		if !good {
			return nil
		}
		in.sent[key] = s
		return &s
	}
	p.SubjectType = str("subject_type", domain.SubjectTypes())
	p.SubjectID = str("subject_id", nil)
	p.Target = str("target", nil)
	p.Effect = str("effect", domain.Effects())
	if x, present := o.Get("params"); present {
		in.sent["params"] = nil
		if x != nil {
			if d, ok := dictField(&c, x, body("params")); ok {
				p.Params, in.sent["params"] = d, d
			}
		}
	}
	p.Condition = str("condition", nil)
	if x, present := o.Get("enabled"); present {
		in.sent["enabled"] = nil
		if x != nil {
			if b, ok := c.Bool(x, body("enabled")); ok {
				p.Enabled, in.sent["enabled"] = &b, b
			}
		}
	}
	if x, present := o.Get("priority"); present {
		in.sent["priority"] = nil
		if x != nil {
			if n, ok := priority(&c, x); ok {
				p.Priority, in.sent["priority"] = &n, n
			}
		}
	}
	c.Extra(o, ruleFields(), body())
	*errs = append(*errs, c.Errs...)
}

// ruleJSON is PolicyRuleResponse.
func ruleJSON(r domain.Rule) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: r.ID},
		{Key: "enabled", Value: r.Enabled},
		{Key: "priority", Value: r.Priority},
		{Key: "subject_type", Value: r.SubjectType},
		{Key: "subject_id", Value: r.SubjectID},
		{Key: "target", Value: r.Target},
		{Key: "effect", Value: r.Effect},
		{Key: "params", Value: r.Params},
		{Key: "condition", Value: r.Condition},
	}
}

func (s *Server) ListPolicyRulesV1PoliciesGet(ctx context.Context, _ gen.ListPolicyRulesV1PoliciesGetRequestObject) (gen.ListPolicyRulesV1PoliciesGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	rules, err := s.svc.ListRules(ctx, c, inputFrom(ctx).filter)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(rules))
	for i, r := range rules {
		out[i] = ruleJSON(r)
	}
	return ok(out), nil
}

func (s *Server) CreatePolicyRuleV1PoliciesPost(ctx context.Context, _ gen.CreatePolicyRuleV1PoliciesPostRequestObject) (gen.CreatePolicyRuleV1PoliciesPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.admin(ctx); err != nil {
		return nil, err
	}
	r := inputFrom(ctx).rule
	saved, err := s.svc.CreateRule(ctx, c, r)
	if err != nil {
		return nil, err
	}
	// The response is the row as flushed: its params are the request's, in their order.
	saved.Params = r.Params
	return created(ruleJSON(saved)), nil
}

func ruleID(ctx context.Context) uuid.UUID {
	return uuid.MustParse(inputFrom(ctx).path["rule_id"])
}

func (s *Server) GetPolicyRuleV1PoliciesRuleIdGet(ctx context.Context, _ gen.GetPolicyRuleV1PoliciesRuleIdGetRequestObject) (gen.GetPolicyRuleV1PoliciesRuleIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	r, err := s.svc.GetRule(ctx, c, ruleID(ctx))
	if err != nil {
		return nil, err
	}
	return ok(ruleJSON(r)), nil
}

func (s *Server) UpdatePolicyRuleV1PoliciesRuleIdPatch(ctx context.Context, _ gen.UpdatePolicyRuleV1PoliciesRuleIdPatchRequestObject) (gen.UpdatePolicyRuleV1PoliciesRuleIdPatchResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.admin(ctx); err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	r, err := s.svc.UpdateRule(ctx, c, ruleID(ctx), func(existing domain.Rule) domain.Rule {
		return withSent(existing, in.sent)
	}, in.patch)
	if err != nil {
		return nil, err
	}
	if in.patch.Params != nil {
		r.Params = in.patch.Params
	}
	return ok(ruleJSON(r)), nil
}

// withSent is existing.model_copy(update=fields): a sent null replaces the
// value too. A null target reads as None, an absent effect falls through
// every check (domain.AssertEnforceable).
func withSent(r domain.Rule, sent map[string]any) domain.Rule {
	str := func(key string, dst *string, null *bool) {
		v, ok := sent[key]
		if !ok {
			return
		}
		if v == nil {
			*dst = ""
			if null != nil {
				*null = true
			}
			return
		}
		*dst = v.(string)
	}
	str("subject_type", &r.SubjectType, nil)
	str("subject_id", &r.SubjectID, nil)
	str("target", &r.Target, &r.TargetNull)
	str("effect", &r.Effect, nil)
	if v, ok := sent["params"]; ok {
		r.Params = v
	}
	if v, ok := sent["condition"]; ok {
		if v == nil {
			r.Condition = nil
		} else {
			s := v.(string)
			r.Condition = &s
		}
	}
	return r
}

func (s *Server) DeletePolicyRuleV1PoliciesRuleIdDelete(ctx context.Context, _ gen.DeletePolicyRuleV1PoliciesRuleIdDeleteRequestObject) (gen.DeletePolicyRuleV1PoliciesRuleIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.admin(ctx); err != nil {
		return nil, err
	}
	if err := s.svc.DeleteRule(ctx, c, ruleID(ctx)); err != nil {
		return nil, err
	}
	return noContent(), nil
}
