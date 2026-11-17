//go:build suite

// Package governance pins the policies, effective-policy, audit-log, secrets
// and egress-exit routes (.omc/research/go-migration/dossiers/governance.md).
package governance

import (
	"net/http"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

const notAdmin = "Only a workspace admin may perform this action"

func httpError(status int, detail string) map[string]any {
	return h.Problem(status, "http_error", detail)
}

func rule(id any, w *h.Workspace, target, effect string, params map[string]any, priority int) map[string]any {
	return map[string]any{
		"id": id, "enabled": true, "priority": priority, "subject_type": "workspace", "subject_id": w.ID,
		"target": target, "effect": effect, "params": params, "condition": nil,
	}
}

func TestNewWorkspaceIsSeededWithTheBaseline(t *testing.T) {
	w := h.NewWorkspace(t)
	month := map[string]any{"amount_usd": "500.00", "period": "month"}
	w.Owner.Get(t, w.Path("/policies?effect=cap&target=spend")).Expect(http.StatusOK).
		Match(h.Contains(rule(h.AnyUUID, w, "spend", "cap", month, 0)))
	preview := w.Owner.Post(t, w.Path("/governance/effective-policy/preview"), map[string]any{}).Expect(http.StatusOK).Object()
	budget, _ := preview["effective_policy"].(map[string]any)["budget"].(map[string]any)
	if budget["monthly_spend_cap_usd"] != "500.00" || budget["run_budget_usd"] != "50.00" {
		t.Fatalf("baseline budget %v", budget)
	}
}

func TestPolicyRuleLifecycle(t *testing.T) {
	w := h.NewWorkspace(t)
	body := map[string]any{"subject_type": "workspace", "subject_id": w.ID, "target": "tool:delete_repo", "effect": "deny", "priority": 3}
	created := w.Owner.Post(t, w.Path("/policies"), body).Expect(http.StatusCreated).
		Match(rule(h.AnyUUID, w, "tool:delete_repo", "deny", map[string]any{}, 3)).Object()
	id := created["id"].(string)

	w.Owner.Get(t, w.Path("/policies/"+id)).Expect(http.StatusOK).Match(created)
	w.Owner.Patch(t, w.Path("/policies/"+id), map[string]any{"priority": 9}).Expect(http.StatusOK).
		Match(rule(id, w, "tool:delete_repo", "deny", map[string]any{}, 9))
	w.Owner.Patch(t, w.Path("/policies/"+id), map[string]any{"target": "tool:*"}).Expect(http.StatusUnprocessableEntity).
		Match(httpError(http.StatusUnprocessableEntity, "deny requires a specific tool (tool:<name>), not a wildcard 'tool:*'"))
	w.Owner.Get(t, w.Path("/policies?effect=deny")).Expect(http.StatusOK).
		Match([]any{rule(id, w, "tool:delete_repo", "deny", map[string]any{}, 9)})

	w.Owner.Get(t, w.Path("/audit-logs/?resource_id="+id)).Expect(http.StatusOK).Match(map[string]any{
		"events": h.Contains(
			map[string]any{
				"id": h.AnyUUID, "created_at": h.AnyTimestamp, "actor_id": w.People.Owner.ID, "actor_type": "user",
				"workspace_id": w.ID, "source_ip": h.Any, "user_agent": h.Any, "request_id": h.Any,
				"action": "governance_policy.create", "resource_type": "governance_policy", "resource_id": id,
				"changes": nil, "event_metadata": h.Any,
			},
		),
		"next_cursor": nil,
	})

	w.Owner.Delete(t, w.Path("/policies/"+id)).Expect(http.StatusNoContent)
	w.Owner.Get(t, w.Path("/policies/"+id)).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Policy rule not found"))
	w.Owner.Delete(t, w.Path("/policies/"+id)).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Policy rule not found"))
}

func TestPoliciesAreAdminOnly(t *testing.T) {
	w := h.NewWorkspace(t)
	body := map[string]any{"subject_type": "workspace", "subject_id": w.ID, "target": "tool:x", "effect": "deny"}
	w.Member.Get(t, w.Path("/policies")).Expect(http.StatusForbidden).Match(httpError(http.StatusForbidden, notAdmin))
	w.Member.Post(t, w.Path("/policies"), body).Expect(http.StatusForbidden).Match(httpError(http.StatusForbidden, notAdmin))
	w.Member.Get(t, w.Path("/audit-logs/")).Expect(http.StatusForbidden).Match(httpError(http.StatusForbidden, notAdmin))
	// requires_workspace_admin answers before the query is read; the create route validates first.
	w.Member.Get(t, w.Path("/policies?effect=nope")).Expect(http.StatusForbidden)
	w.Member.Post(t, w.Path("/policies"), map[string]any{}).Expect(http.StatusUnprocessableEntity)

	w.Outsider.Get(t, w.Path("/policies")).Expect(http.StatusForbidden).
		Match(httpError(http.StatusForbidden, "User is not a member of the requested workspace"))
	w.Anonymous.Get(t, w.Path("/policies")).Expect(http.StatusUnauthorized)

	// The preview needs membership, not admin.
	w.Member.Post(t, w.Path("/governance/effective-policy/preview"), map[string]any{}).Expect(http.StatusOK)
	w.APIKey(t).Post(t, w.Path("/governance/effective-policy/preview"), map[string]any{}).Expect(http.StatusOK)
}

func TestPreviewRefusesALooserTaskPolicy(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/policies"), map[string]any{
		"subject_type": "workspace", "subject_id": w.ID, "target": "spend", "effect": "cap",
		"params": map[string]any{"amount_usd": "5.00", "period": "run"},
	}).Expect(http.StatusCreated)
	w.Owner.Post(t, w.Path("/governance/effective-policy/preview"), map[string]any{
		"task_policy": map[string]any{"budget": map[string]any{"run_budget_usd": "500"}},
	}).Expect(http.StatusUnprocessableEntity)
	got := w.Owner.Post(t, w.Path("/governance/effective-policy/preview"), map[string]any{
		"task_policy": map[string]any{"budget": map[string]any{"run_budget_usd": "1.50"}},
	}).Expect(http.StatusOK).Object()
	if b := got["effective_policy"].(map[string]any)["budget"].(map[string]any); b["run_budget_usd"] != "1.50" {
		t.Fatalf("budget %v", b)
	}
	w.Owner.Get(t, w.Path("/audit-logs/?limit=0")).Expect(http.StatusUnprocessableEntity)
}

func TestSecretsLifecycle(t *testing.T) {
	w := h.NewWorkspace(t)
	created := w.Owner.Post(t, w.Path("/secrets"), map[string]any{"name": "suite-token", "value": "s3cret", "description": "for the suite"}).
		Expect(http.StatusCreated).Match(map[string]any{
		"id": h.AnyUUID, "name": "suite-token", "description": "for the suite", "created_at": h.AnyTimestamp,
		"updated_at": h.Any, "used_by": []any{}, "owner": nil,
	}).Object()
	id := created["id"].(string)
	if _, leaked := created["value"]; leaked {
		t.Fatal("the secret value is in the response")
	}

	w.Owner.Post(t, w.Path("/secrets"), map[string]any{"name": "suite-token", "value": "x"}).Expect(http.StatusConflict)
	w.Member.Post(t, w.Path("/secrets"), map[string]any{"name": "OTHER", "value": "x"}).Expect(http.StatusForbidden).
		Match(httpError(http.StatusForbidden, notAdmin))
	w.Owner.Get(t, w.Path("/secrets")).Expect(http.StatusOK).Match(h.Contains(map[string]any{
		"id": id, "name": "suite-token", "description": "for the suite", "created_at": h.AnyTimestamp,
		"updated_at": h.Any, "used_by": []any{}, "owner": nil,
	}))
	w.Owner.Patch(t, w.Path("/secrets/"+id), map[string]any{"description": "changed"}).Expect(http.StatusOK)
	w.Owner.Put(t, w.Path("/secrets/"+id+"/value"), map[string]any{"value": ""}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Put(t, w.Path("/secrets/"+id+"/value"), map[string]any{"value": "rotated"}).Expect(http.StatusOK)
	w.Outsider.Get(t, w.OutsiderPath("/secrets/"+id)).Expect(http.StatusNotFound)

	w.Owner.Delete(t, w.Path("/secrets/"+id)).Expect(http.StatusNoContent)
	w.Owner.Get(t, w.Path("/secrets/"+id)).Expect(http.StatusNotFound)
}

func TestEgressExitsNeedTheEnterpriseEdition(t *testing.T) {
	w := h.NewWorkspace(t)
	gone := httpError(http.StatusNotFound, "egress exits need the enterprise edition")
	w.Owner.Get(t, w.Path("/egress-exits/")).Expect(http.StatusNotFound).Match(gone)
	w.Owner.Post(t, w.Path("/egress-exits/"), map[string]any{}).Expect(http.StatusNotFound).Match(gone)
}
