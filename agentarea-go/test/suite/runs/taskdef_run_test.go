//go:build suite

package runs

import (
	"encoding/json"
	"fmt"
	"net/http"
	"testing"
	"time"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

// POST /task-definitions/{id}/run starts a task of the definition's agent with
// the saved parameters under the call's, and the task runs to completion.
func TestATaskDefinitionRunStartsATask(t *testing.T) {
	w := h.NewWorkspace(t)
	host := &fakeHost{}
	base := host.serve(t)
	cfg := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": suiteProvider, "name": "Fake", "api_key": "sk-suite", "endpoint_url": base,
	}).Expect(http.StatusOK).Object()
	inst := w.Owner.Post(t, w.Path("/model-instances/"), map[string]any{
		"provider_config_id": cfg["id"], "model_spec_id": suiteChat, "name": "Fake chat",
	}).Expect(http.StatusOK).Object()
	agent := w.Owner.Post(t, w.Path("/agents/"), map[string]any{
		"name": "DefRun", "instruction": "Answer the question.", "model_id": inst["id"], "tools": []any{},
	}).Expect(http.StatusOK, http.StatusCreated).Object()["id"].(string)
	def := w.Owner.Post(t, w.Path("/task-definitions/"), map[string]any{
		"name": "Ask", "description": "What is the suite answer?", "agent_id": agent, "parameters": map[string]any{"a": 1, "b": "saved"},
	}).Expect(http.StatusCreated).Object()["id"].(string)
	runPath := w.Path("/task-definitions/" + def + "/run")

	w.Outsider.Post(t, runPath, map[string]any{}).Expect(http.StatusForbidden, http.StatusNotFound)
	w.Anonymous.Post(t, runPath, map[string]any{}).Expect(http.StatusUnauthorized, http.StatusForbidden)

	task := w.Owner.Post(t, runPath, map[string]any{"parameters": map[string]any{"b": "call"}}).
		Expect(http.StatusCreated).Object()
	taskID, _ := task["id"].(string)
	if taskID == "" || task["agent_id"] != agent || task["status"] == nil {
		t.Fatalf("task body %v", task)
	}
	if p, _ := task["provenance"].(map[string]any); p == nil || p["task_definition_id"] != def {
		t.Fatalf("provenance %v", task["provenance"])
	}
	if params, _ := task["parameters"].(map[string]any); params != nil && (params["a"] != json.Number("1") || params["b"] != "call") {
		t.Fatalf("parameters %v", params)
	}

	tasks := "/agents/" + agent + "/tasks/"
	h.Eventually(t, 90*time.Second, func() error {
		got := w.Owner.Get(t, w.Path(tasks+taskID)).Expect(http.StatusOK).Object()
		switch got["status"] {
		case "completed":
			return nil
		case "failed", "cancelled", "canceled":
			t.Fatalf("task ended %v: %v", got["status"], got)
		}
		return fmt.Errorf("status %v", got["status"])
	})
}
