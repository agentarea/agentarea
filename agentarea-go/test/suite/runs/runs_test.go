//go:build suite

// Package runs pins the runs HTTP surface: tasks, inbox and tool-call
// approvals (.omc/research/go-migration/dossiers/runs-surface.md).
package runs

import (
	"net/http"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

func httpError(status int, detail string) map[string]any {
	return h.Problem(status, "http_error", detail)
}

const (
	missingAgent = "00000000-0000-4000-8000-000000000001"
	missingTask  = "00000000-0000-4000-8000-000000000002"
)

func TestEmptyWorkspaceListsNothing(t *testing.T) {
	w := h.NewWorkspace(t)
	for _, c := range []*h.Client{w.Owner, w.Member, w.APIKey(t)} {
		c.Get(t, w.Path("/tasks/")).Expect(http.StatusOK).Match([]any{})
		c.Get(t, w.Path("/inbox/")).Expect(http.StatusOK).
			Match(map[string]any{"items": []any{}, "total": 0.0, "page": 1.0, "page_size": 100.0})
		c.Get(t, w.Path("/tool-call-approvals?status=pending&page_size=10")).Expect(http.StatusOK).
			Match(map[string]any{"items": []any{}, "total": 0.0, "page": 1.0, "page_size": 10.0})
	}
	w.Outsider.Get(t, w.OutsiderPath("/tasks/")).Expect(http.StatusOK).Match([]any{})
}

func TestStrangersAreTurnedAway(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Outsider.Get(t, w.Path("/tasks/")).Expect(http.StatusForbidden).
		Match(httpError(http.StatusForbidden, "User is not a member of the requested workspace"))
	w.Outsider.Get(t, w.Path("/inbox/")).Expect(http.StatusForbidden)
	w.Anonymous.Get(t, w.Path("/tasks/")).Expect(http.StatusUnauthorized)
}

func TestMissingTasksAndAgentsAreNotFound(t *testing.T) {
	w := h.NewWorkspace(t)
	task := "/agents/" + missingAgent + "/tasks/" + missingTask
	w.Owner.Get(t, w.Path("/tasks/"+missingTask)).Expect(http.StatusNotFound).
		Match(httpError(http.StatusNotFound, "Task not found"))
	w.Member.Get(t, w.Path("/agents/"+missingAgent+"/tasks/")).Expect(http.StatusNotFound).
		Match(httpError(http.StatusNotFound, "Agent not found"))
	w.Owner.Get(t, w.Path(task)).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Task not found"))
	w.Owner.Get(t, w.Path(task+"/events")).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Task not found"))
	w.Owner.Get(t, w.Path(task+"/events/stream")).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Task not found"))
	w.Owner.Get(t, w.Path(task+"/summary")).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Task not found"))
	w.Owner.Get(t, w.Path(task+"/escalations")).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Task not found"))
	// A missing task passes the task authority check; the route answers for the agent first.
	w.Member.Delete(t, w.Path(task)).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Agent not found"))
	w.APIKey(t).Post(t, w.Path(task+"/pause"), nil).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Agent not found"))
	w.Owner.Get(t, w.Path("/tool-call-approvals/"+missingTask)).Expect(http.StatusNotFound).
		Match(httpError(http.StatusNotFound, "Approval not found"))
	w.Owner.Get(t, w.Path("/tool-call-approvals/not-a-uuid")).Expect(http.StatusNotFound)
}

func TestParametersAreValidatedTogether(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Get(t, w.Path("/inbox/?status=running&page=0")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, w.Path("/tasks/?limit=1001")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, w.Path("/tool-call-approvals?status=open")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, w.Path("/agents/nope/tasks/")).Expect(http.StatusUnprocessableEntity)
	task := "/agents/" + missingAgent + "/tasks/" + missingTask
	w.Owner.Post(t, w.Path(task+"/resolve-escalation"), map[string]any{}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path(task+"/input"), map[string]any{"input_request_id": "", "extra": 1}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path("/tool-call-approvals/"+missingTask+"/decide"), map[string]any{"approved": "maybe"}).
		Expect(http.StatusUnprocessableEntity)
}

func TestDecidingAMissingApprovalIsNotFound(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Member.Post(t, w.Path("/tool-call-approvals/"+missingTask+"/decide"), map[string]any{"approved": true}).
		Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Approval not found"))
}

func newAgent(t *testing.T, w *h.Workspace) string {
	t.Helper()
	return w.Owner.Post(t, w.Path("/agents/"), map[string]any{"name": "Runner", "tools": []any{}}).
		Expect(http.StatusOK, http.StatusCreated).Object()["id"].(string)
}

func TestStartingARunValidatesTheRequestAndTheAgent(t *testing.T) {
	w := h.NewWorkspace(t)
	agent := newAgent(t, w)
	tasks := "/agents/" + agent + "/tasks"
	w.Owner.Post(t, w.Path(tasks+"/sync"), map[string]any{"description": "x", "parameters": map[string]any{"session": map[string]any{}}}).
		Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path(tasks+"/schedule"), map[string]any{"description": "x", "scheduled_at": "2030-01-01T10:00:00"}).
		Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, w.Path(tasks+"/sync"), map[string]any{"description": "x", "end_user_id": "eu-1"}).
		Expect(http.StatusForbidden).Match(httpError(http.StatusForbidden, "metadata, end_user_id and webhook can only be set with an API key"))
	// The workspace's baseline caps a run at 50 USD; a run's own policy may only tighten it.
	w.Owner.Post(t, w.Path(tasks+"/sync"), map[string]any{"description": "x", "task_policy": map[string]any{"budget": map[string]any{"run_budget_usd": "100.00"}}}).
		Expect(http.StatusUnprocessableEntity).Match(httpError(http.StatusUnprocessableEntity, "Task policy rejected"))
	w.Owner.Post(t, w.Path(tasks+"/sync"), map[string]any{"description": "x"}).
		Expect(http.StatusUnprocessableEntity).Match(httpError(http.StatusUnprocessableEntity, "Agent model is not configured"))
	limits := map[string]any{
		"budget":    map[string]any{"run_budget_usd": "1.00"},
		"tokens":    map[string]any{"max_tokens": 1000, "max_tokens_per_call": 100},
		"execution": map[string]any{"max_model_turns": 3, "max_tool_calls_per_turn": 2, "max_tool_calls_total": 5},
	}
	w.Owner.Post(t, w.Path(tasks+"/sync"), map[string]any{"description": "x", "task_policy": limits}).
		Expect(http.StatusUnprocessableEntity).Match(httpError(http.StatusUnprocessableEntity, "Agent model is not configured"))
	w.Owner.Get(t, w.Path("/tasks/")).Expect(http.StatusOK).Match([]any{})
}

func TestContinuingAndRetryingMissingRuns(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/tasks/"+missingTask+"/continue"), map[string]any{}).Expect(http.StatusUnprocessableEntity).
		Match(httpError(http.StatusUnprocessableEntity, "At least one continuation resource must be granted"))
	w.Owner.Post(t, w.Path("/tasks/"+missingTask+"/continue"), map[string]any{"additional_iterations": 1}).
		Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Task not found"))
	w.Owner.Post(t, w.Path("/tasks/"+missingTask+"/continue"), map[string]any{"additional_iterations": 1001}).
		Expect(http.StatusUnprocessableEntity)
	task := "/agents/" + missingAgent + "/tasks/" + missingTask
	w.Owner.Post(t, w.Path(task+"/retry"), nil).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Agent not found"))
	w.Owner.Get(t, w.Path(task+"/status")).Expect(http.StatusNotFound).Match(httpError(http.StatusNotFound, "Task not found"))
}
