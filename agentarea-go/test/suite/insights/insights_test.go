//go:build suite

// Package insights pins the dashboard, the agent overview, the workspace
// settings and the network routes
// (.omc/research/go-migration/dossiers/insights.md).
package insights

import (
	"net/http"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

// seededCap is the monthly spend cap every new workspace is seeded with.
const seededCap = "500.00"

func newAgent(t *testing.T, w *h.Workspace, name string) string {
	t.Helper()
	return w.Owner.Post(t, w.Path("/agents/"), map[string]any{"name": name, "instruction": "work", "tools": []any{}}).Expect(http.StatusOK).Object()["id"].(string)
}

func TestDashboardOfAFreshWorkspace(t *testing.T) {
	w := h.NewWorkspace(t)
	body := w.Member.Get(t, w.Path("/dashboard")).Expect(http.StatusOK).Match(map[string]any{
		"spend": map[string]any{
			"today_usd": "0", "mtd_usd": "0", "cap_usd": seededCap, "pct_of_cap": h.AnyNumber, "projected_eom_usd": h.AnyString,
			"projection_method": "trailing-7d", "not_covered": []any{}, "mtd_estimate_usd": "0",
		},
		"blockers":     map[string]any{"hitl": []any{}, "awaiting_continuation": []any{}, "blocked_24h": []any{}, "wallet_exhausted": []any{}, "failed_24h": []any{}},
		"active_tasks": []any{}, "recent_tasks": []any{},
		"schedule":    map[string]any{"horizon_days": 42, "runs": []any{}, "frequent": []any{}},
		"daily_spend": h.Any, "top_agents": []any{},
		"health": map[string]any{"connections": []any{}, "triggers": []any{}},
		"usage":  h.Any,
	}).Object()
	if days := body["daily_spend"].([]any); len(days) != 30 {
		t.Fatalf("daily_spend has %d days, want 30", len(days))
	}
	w.Anonymous.Get(t, w.Path("/dashboard")).Expect(http.StatusUnauthorized)
	w.Outsider.Get(t, w.Path("/dashboard")).Expect(http.StatusForbidden, http.StatusNotFound)
}

func TestSettingsCapRoundTrip(t *testing.T) {
	w := h.NewWorkspace(t)
	path := w.Path("/settings")
	w.Member.Get(t, path).Expect(http.StatusOK).Match(map[string]any{"monthly_cap_usd": seededCap})
	w.Owner.Put(t, path, map[string]any{"monthly_cap_usd": "120.50"}).Expect(http.StatusOK).Match(map[string]any{"monthly_cap_usd": "120.50"})
	w.Member.Get(t, path).Expect(http.StatusOK).Match(map[string]any{"monthly_cap_usd": "120.50"})
	w.Member.Get(t, w.Path("/dashboard")).Expect(http.StatusOK)
	w.Owner.Put(t, path, map[string]any{"monthly_cap_usd": 80}).Expect(http.StatusOK).Match(map[string]any{"monthly_cap_usd": "80"})
	w.Owner.Put(t, path, map[string]any{"monthly_cap_usd": nil}).Expect(http.StatusOK).Match(map[string]any{"monthly_cap_usd": nil})
	w.Member.Get(t, path).Expect(http.StatusOK).Match(map[string]any{"monthly_cap_usd": nil})
}

func TestSettingsWritesAreAdminOnlyAndValidated(t *testing.T) {
	w := h.NewWorkspace(t)
	path := w.Path("/settings")
	w.Member.Put(t, path, map[string]any{"monthly_cap_usd": "5"}).Expect(http.StatusForbidden)
	w.Owner.Put(t, path, map[string]any{}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Put(t, path, map[string]any{"monthly_cap_usd": "-1"}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Put(t, path, map[string]any{"monthly_cap_usd": "lots"}).Expect(http.StatusUnprocessableEntity)
	w.Member.Get(t, path).Expect(http.StatusOK).Match(map[string]any{"monthly_cap_usd": seededCap})
}

func TestAgentOverview(t *testing.T) {
	w := h.NewWorkspace(t)
	agent := newAgent(t, w, "Scout")
	body := w.Member.Get(t, w.Path("/agents/"+agent+"/overview")).Expect(http.StatusOK).Match(map[string]any{
		"cost_today_usd": "0", "cost_mtd_usd": "0", "tasks_done_today": 0, "tasks_failed_today": 0, "last_activity_at": nil,
		"daily_spend": h.Any, "daily_tasks": h.Any, "upcoming": []any{},
	}).Object()
	if n := len(body["daily_tasks"].([]any)); n != 14 {
		t.Fatalf("daily_tasks has %d days, want 14", n)
	}
	w.Member.Get(t, w.Path("/agents/00000000-0000-0000-0000-000000000000/overview")).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Agent not found"))
	w.Member.Get(t, w.Path("/agents/not-a-uuid/overview")).Expect(http.StatusUnprocessableEntity)
}

func TestNetworkTopologyAndPeopleAccess(t *testing.T) {
	w := h.NewWorkspace(t)
	agent := newAgent(t, w, "Scout")
	w.Member.Get(t, w.Path("/network/topology")).Expect(http.StatusOK).Match(map[string]any{
		"nodes":           h.Contains(map[string]any{"id": agent, "type": "agent", "label": "Scout", "status": h.AnyString, "metadata": h.Any}),
		"edges":           []any{},
		"governance":      h.Any,
		"deployment_mode": h.AnyString,
	})
	w.Member.Get(t, w.Path("/network/people-access")).Expect(http.StatusForbidden)
	w.Owner.Get(t, w.Path("/network/people-access")).Expect(http.StatusOK).Match(map[string]any{
		"workspace_id": w.ID, "people": h.Any, "access": h.Contains(map[string]any{"user_id": h.AnyString, "agent_id": agent, "allowed": true, "reason": h.AnyString}),
		"complete": true, "total_people": h.AnyNumber, "total_agents": 1,
		"decision_source": "agent_edge_admission", "directory_status": "available",
	})
}
