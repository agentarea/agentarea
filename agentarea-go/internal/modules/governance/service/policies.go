package service

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/store"
)

// ErrRuleNotFound is a rule id the workspace does not have.
var ErrRuleNotFound = errors.New("Policy rule not found") //nolint:staticcheck // Python's detail

// Filter narrows a rule list.
type Filter = store.Filter

// RulePatch is the fields a PATCH sent; nil was not sent or was null.
type RulePatch = store.Patch

func (sv *Service) known(ctx context.Context, rules []domain.Rule) []domain.Rule {
	out := rules[:0]
	for _, r := range rules {
		if !r.Known() {
			sv.d.Log.WarnContext(ctx, "skipping policy: unsupported effect/subject_type", "policy_id", r.ID, "effect", r.Effect, "subject_type", r.SubjectType)
			continue
		}
		out = append(out, r)
	}
	return out
}

// ListRules is the workspace's rules (GovernancePolicyService.list_rules).
func (sv *Service) ListRules(ctx context.Context, c authn.Caller, f Filter) ([]domain.Rule, error) {
	s, done, err := sv.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	defer done()
	rules, err := sv.d.Policies.List(ctx, s, f)
	if err != nil {
		return nil, err
	}
	return sv.known(ctx, rules), nil
}

// GetRule is one rule; ErrRuleNotFound when absent or of an unknown kind.
func (sv *Service) GetRule(ctx context.Context, c authn.Caller, id uuid.UUID) (domain.Rule, error) {
	s, done, err := sv.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return domain.Rule{}, err
	}
	defer done()
	return sv.getRule(ctx, s, id)
}

func (sv *Service) getRule(ctx context.Context, s db.Session, id uuid.UUID) (domain.Rule, error) {
	r, ok, err := sv.d.Policies.Get(ctx, s, id)
	if err != nil {
		return domain.Rule{}, err
	}
	if !ok || !r.Known() {
		if ok {
			sv.d.Log.WarnContext(ctx, "skipping policy: unsupported effect/subject_type", "policy_id", r.ID, "effect", r.Effect, "subject_type", r.SubjectType)
		}
		return domain.Rule{}, ErrRuleNotFound
	}
	return r, nil
}

// CreateRule checks the rule is enforceable, inserts it as the caller's and
// records governance_policy.create. The caller is a workspace admin.
func (sv *Service) CreateRule(ctx context.Context, c authn.Caller, r domain.Rule) (domain.Rule, error) {
	if err := domain.AssertEnforceable(r); err != nil {
		return domain.Rule{}, err
	}
	var created domain.Rule
	err := sv.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, s db.Session) error {
		var err error
		created, err = sv.createRule(ctx, s, c.UserID, r)
		if err != nil {
			return err
		}
		sv.recordSwallowed(ctx, s, c, "governance_policy.create", created.ID)
		return nil
	})
	return created, err
}

func (sv *Service) createRule(ctx context.Context, s db.Session, createdBy string, r domain.Rule) (domain.Rule, error) {
	return sv.d.Policies.Create(ctx, s, uuid.New(), createdBy, r, sv.d.Now())
}

// UpdateRule checks the rule as it would read after the patch, then writes
// the sent non-null fields (repository.update skips None) and records
// governance_policy.update without a diff. sent applies the patch as sent,
// nulls included, for the check (model_copy(update=...)).
func (sv *Service) UpdateRule(ctx context.Context, c authn.Caller, id uuid.UUID, sent func(domain.Rule) domain.Rule, p RulePatch) (domain.Rule, error) {
	var updated domain.Rule
	err := sv.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, s db.Session) error {
		existing, err := sv.getRule(ctx, s, id)
		if err != nil {
			return err
		}
		if err := domain.AssertEnforceable(sent(existing)); err != nil {
			return err
		}
		r, ok, err := sv.d.Policies.Update(ctx, s, id, p, sv.d.Now().UTC())
		if err != nil {
			return err
		}
		if !ok || !r.Known() {
			return ErrRuleNotFound
		}
		sv.recordSwallowed(ctx, s, c, "governance_policy.update", id.String())
		updated = r
		return nil
	})
	return updated, err
}

// DeleteRule removes the rule and records governance_policy.delete.
func (sv *Service) DeleteRule(ctx context.Context, c authn.Caller, id uuid.UUID) error {
	return sv.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, s db.Session) error {
		deleted, err := sv.d.Policies.Delete(ctx, s, id)
		if err != nil {
			return err
		}
		if !deleted {
			return ErrRuleNotFound
		}
		sv.recordSwallowed(ctx, s, c, "governance_policy.delete", id.String())
		return nil
	})
}
