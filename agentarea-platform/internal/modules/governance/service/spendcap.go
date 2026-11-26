package service

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/store"
)

var _ api.SpendCaps = (*Service)(nil)

// spendCapScopeKeys narrow a spend cap to part of the spend (SPEND_CAP_SCOPE_KEYS).
func spendCapScopeKeys() []string {
	return []string{"client_id", "connection_id", "tool", "model", "currency", "category"}
}

// workspaceCapScopeKeys are the keys workspace_cap_currencies treats as narrowing;
// currency is the cap's own currency there.
func workspaceCapScopeKeys() []string {
	return []string{"category", "client_id", "connection_id", "tool", "model"}
}

func paramOf(r domain.Rule, key string) any {
	if o, ok := r.Params.(wirejson.Object); ok {
		v, _ := o.Get(key)
		return v
	}
	return nil
}

// truthy is Python's bool() of a decoded JSON value.
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case json.Number:
		f, err := x.Float64()
		return err != nil || f != 0
	case wirejson.Float:
		return x != 0
	case []any:
		return len(x) > 0
	case wirejson.Object:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}

func monthly(r domain.Rule, scopeKeys []string) bool {
	if p := paramOf(r, "period"); p != nil && p != "month" {
		return false
	}
	for _, k := range scopeKeys {
		if truthy(paramOf(r, k)) {
			return false
		}
	}
	return true
}

func pyStr(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case json.Number:
		return x.String()
	case wirejson.Float:
		return wirejson.FormatFloat(float64(x))
	case bool:
		if x {
			return "True"
		}
		return "False"
	}
	return fmt.Sprint(v)
}

func (sv *Service) workspaceSpendCaps(ctx context.Context, s db.Session, enabledOnly bool) ([]domain.Rule, error) {
	st, sid, eff, tgt := "workspace", s.Workspace().ID(), "cap", "spend"
	f := store.Filter{SubjectType: &st, SubjectID: &sid, Effect: &eff, Target: &tgt}
	if enabledOnly {
		on := true
		f.Enabled = &on
	}
	rules, err := sv.d.Policies.List(ctx, s, f)
	if err != nil {
		return nil, err
	}
	return sv.known(ctx, rules), nil
}

func (sv *Service) readCaps(ctx context.Context, ws scope.Workspace) ([]domain.Rule, error) {
	s, done, err := sv.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer done()
	return sv.workspaceSpendCaps(ctx, s, true)
}

// MonthlyCap implements api.SpendCaps (_get_workspace_policy_cap_usd). An
// amount that is not a number reads as 0, as to_money does.
func (sv *Service) MonthlyCap(ctx context.Context, ws scope.Workspace) (*money.Decimal, error) {
	rules, err := sv.readCaps(ctx, ws)
	if err != nil {
		return nil, err
	}
	for _, r := range rules {
		if !monthly(r, spendCapScopeKeys()) {
			continue
		}
		if a := paramOf(r, "amount_usd"); a != nil {
			d, err := money.Parse(pyStr(a))
			if err != nil {
				d = money.Zero()
			}
			return &d, nil
		}
	}
	return nil, nil
}

// CapCurrencies implements api.SpendCaps.
func (sv *Service) CapCurrencies(ctx context.Context, ws scope.Workspace, billing string) (map[string]bool, error) {
	rules, err := sv.readCaps(ctx, ws)
	if err != nil {
		return nil, err
	}
	out := map[string]bool{}
	for _, r := range rules {
		if !monthly(r, workspaceCapScopeKeys()) {
			continue
		}
		cur := billing
		if c := paramOf(r, "currency"); truthy(c) {
			cur = pyStr(c)
		}
		out[cur] = true
	}
	return out, nil
}

// SetMonthlyCap implements api.SpendCaps (update_workspace_settings). Each
// rule written or removed is recorded as the policy routes record it.
func (sv *Service) SetMonthlyCap(ctx context.Context, c authn.Caller, amount *money.Decimal) error {
	var params wirejson.Object
	var cap domain.Rule
	if amount != nil {
		params = wirejson.Object{{Key: "amount_usd", Value: amount.String()}, {Key: "period", Value: "month"}}
		cap = domain.Rule{SubjectType: "workspace", SubjectID: c.Workspace.ID(), Target: "spend", Effect: "cap", Params: params, Enabled: true}
		if err := domain.AssertEnforceable(cap); err != nil {
			return &api.CapRefused{Detail: err.Error()}
		}
	}
	return sv.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, s db.Session) error {
		all, err := sv.workspaceSpendCaps(ctx, s, false)
		if err != nil {
			return err
		}
		var existing []domain.Rule
		for _, r := range all {
			if monthly(r, spendCapScopeKeys()) {
				existing = append(existing, r)
			}
		}
		drop := existing
		if amount != nil {
			if len(existing) == 0 {
				created, err := sv.createRule(ctx, s, c.UserID, cap)
				if err != nil {
					return err
				}
				sv.recordSwallowed(ctx, s, c, "governance_policy.create", created.ID)
				return nil
			}
			on := true
			if _, _, err := sv.d.Policies.Update(ctx, s, uuid.MustParse(existing[0].ID), store.Patch{Params: params, Enabled: &on}, sv.d.Now().UTC()); err != nil {
				return err
			}
			sv.recordSwallowed(ctx, s, c, "governance_policy.update", existing[0].ID)
			drop = existing[1:]
		}
		for _, r := range drop {
			if _, err := sv.d.Policies.Delete(ctx, s, uuid.MustParse(r.ID)); err != nil {
				return err
			}
			sv.recordSwallowed(ctx, s, c, "governance_policy.delete", r.ID)
		}
		return nil
	})
}
