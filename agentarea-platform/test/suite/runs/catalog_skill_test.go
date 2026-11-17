//go:build suite

package runs

import (
	"fmt"
	"net/http"
	"slices"
	"strings"
	"testing"
	"time"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

// suiteSkillItem is the catalog skill test/suite/catalog/seed.sql applies.
const suiteSkillItem = "5e1f0000-0000-4000-8000-000000000111"

// A skill installed from the catalog is offered to the agent's run: listed in
// its system prompt with activate_skill among its tools.
func TestACatalogSkillIsOfferedInARun(t *testing.T) {
	w := h.NewWorkspace(t)
	host := &fakeHost{}
	base := host.serve(t)
	cfg := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": suiteProvider, "name": "Fake", "api_key": "sk-suite", "endpoint_url": base,
	}).Expect(http.StatusOK).Object()
	inst := w.Owner.Post(t, w.Path("/model-instances/"), map[string]any{
		"provider_config_id": cfg["id"], "model_spec_id": suiteChat, "name": "Fake chat",
	}).Expect(http.StatusOK).Object()
	skill := w.Owner.Post(t, w.Path("/skills/"+suiteSkillItem+"/install"), nil).Expect(http.StatusOK).Object()["id"].(string)
	agent := w.Owner.Post(t, w.Path("/agents/"), map[string]any{
		"name": "Skilled", "instruction": "Answer the question.", "model_id": inst["id"], "tools": []any{},
		"skill_ids": []any{skill},
	}).Expect(http.StatusOK, http.StatusCreated).Object()["id"].(string)

	tasks := "/agents/" + agent + "/tasks/"
	taskID, _ := w.Owner.Post(t, w.Path(tasks+"sync"), map[string]any{"description": "Which word?"}).
		Expect(http.StatusOK).Object()["id"].(string)
	h.Eventually(t, 90*time.Second, func() error {
		got := w.Owner.Get(t, w.Path(tasks+taskID)).Expect(http.StatusOK).Object()
		switch got["status"] {
		case "completed", "failed", "cancelled", "canceled":
			return nil
		}
		return fmt.Errorf("status %v", got["status"])
	})

	host.mu.Lock()
	defer host.mu.Unlock()
	if len(host.requests) == 0 {
		t.Fatal("the run never called the model")
	}
	first := host.requests[0]
	if !slices.Contains(toolNames(first), "activate_skill") {
		t.Fatalf("activate_skill not offered: %v", toolNames(first))
	}
	msgs, _ := first["messages"].([]any)
	system, _ := msgs[0].(map[string]any)["content"].(string)
	if !strings.Contains(system, "**suite-helper**: Answers with the suite word") {
		t.Fatalf("the skill is not in the system prompt: %s", system)
	}
}
