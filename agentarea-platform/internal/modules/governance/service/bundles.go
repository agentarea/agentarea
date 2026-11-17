package service

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
)

// BundleRules is what a bundle deploy reads and writes of governance rules.
type BundleRules struct{ S *Service }

var _ catalogapi.BundleRules = BundleRules{}

func ruleOf(r catalogapi.BundleRule) domain.Rule {
	return domain.Rule{Enabled: r.Enabled, Priority: r.Priority, SubjectType: r.SubjectType, SubjectID: r.SubjectID,
		Target: r.Target, Effect: r.Effect, Params: r.Params, Condition: r.Condition}
}

func (BundleRules) RuleProblem(r catalogapi.BundleRule) string {
	if err := domain.AssertEnforceable(ruleOf(r)); err != nil {
		return err.Error()
	}
	return ""
}

// sameJSON is Python's == over two JSON values: an int equals the float of its value.
func sameJSON(a, b any) (bool, error) {
	norm := func(v any) (any, error) {
		raw, err := json.Marshal(v)
		if err != nil {
			return nil, err
		}
		var out any
		return out, json.Unmarshal(raw, &out)
	}
	x, err := norm(a)
	if err != nil {
		return false, err
	}
	y, err := norm(b)
	if err != nil {
		return false, err
	}
	return reflect.DeepEqual(x, y), nil
}

func sameCondition(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}

func (b BundleRules) MatchingRule(ctx context.Context, c authn.Caller, r catalogapi.BundleRule) (string, bool, error) {
	subjectType, subjectID, target, effect := r.SubjectType, r.SubjectID, r.Target, r.Effect
	rules, err := b.S.ListRules(ctx, c, Filter{SubjectType: &subjectType, SubjectID: &subjectID, Target: &target, Effect: &effect})
	if err != nil {
		return "", false, err
	}
	params := r.Params
	if params == nil {
		params = map[string]any{}
	}
	for _, x := range rules {
		existing := x.Params
		if existing == nil {
			existing = map[string]any{}
		}
		same, err := sameJSON(existing, params)
		if err != nil {
			return "", false, err
		}
		if same && sameCondition(x.Condition, r.Condition) {
			return x.ID, x.ID != "", nil
		}
	}
	return "", false, nil
}

func (b BundleRules) RuleLive(ctx context.Context, c authn.Caller, id string) (bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return false, nil
	}
	_, err = b.S.GetRule(ctx, c, u)
	switch {
	case errors.Is(err, ErrRuleNotFound):
		return false, nil
	case err != nil:
		return false, err
	}
	return true, nil
}

func (b BundleRules) CreateRule(ctx context.Context, c authn.Caller, r catalogapi.BundleRule) (string, error) {
	created, err := b.S.CreateRule(ctx, c, ruleOf(r))
	return created.ID, err
}

func (b BundleRules) UpdateRule(ctx context.Context, c authn.Caller, id string, r catalogapi.BundleRule, setEnabled bool) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return catalogapi.ErrBundleEntityGone
	}
	want := ruleOf(r)
	p := RulePatch{SubjectType: &want.SubjectType, SubjectID: &want.SubjectID, Target: &want.Target, Effect: &want.Effect,
		Condition: want.Condition, Params: want.Params, Priority: &want.Priority}
	if setEnabled {
		p.Enabled = &want.Enabled
	}
	_, err = b.S.UpdateRule(ctx, c, u, func(existing domain.Rule) domain.Rule {
		next := want
		next.ID = existing.ID
		if !setEnabled {
			next.Enabled = existing.Enabled
		}
		return next
	}, p)
	if errors.Is(err, ErrRuleNotFound) {
		return catalogapi.ErrBundleEntityGone
	}
	return err
}

func (b BundleRules) DeleteRule(ctx context.Context, c authn.Caller, id string) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	return b.S.DeleteRule(ctx, c, u)
}
