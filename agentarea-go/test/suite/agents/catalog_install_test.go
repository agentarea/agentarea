//go:build suite

package agents

import (
	"net/http"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

// The catalog rows test/suite/catalog/seed.sql applies.
const (
	suiteSkillItem  = "5e1f0000-0000-4000-8000-000000000111"
	suitePresetItem = "5e1f0000-0000-4000-8000-000000000112"
)

func TestCreateWithTriggersAndAnApprovalTool(t *testing.T) {
	w := h.NewWorkspace(t)
	body := map[string]any{
		"name": "Nightly", "instruction": "Report", "tools": []any{
			map[string]any{"type": "code", "name": "agentarea/files", "settings": map[string]any{"requires_user_confirmation": true}},
		},
		"triggers": []any{map[string]any{"name": "nightly", "trigger_type": "cron", "cron_expression": "0 3 * * *",
			"task_parameters": map[string]any{"text": "Report the night"}}},
	}

	bad := map[string]any{}
	for k, v := range body {
		bad[k] = v
	}
	bad["name"] = "Broken"
	bad["triggers"] = []any{map[string]any{"name": "nightly", "trigger_type": "cron", "cron_expression": "not a cron",
		"task_parameters": map[string]any{"text": "x"}}}
	w.Owner.Post(t, w.Path("/agents/"), bad).Expect(http.StatusBadRequest)
	for _, a := range w.Owner.Get(t, w.Path("/agents/")).Expect(http.StatusOK).Array() {
		if a.(map[string]any)["name"] == "Broken" {
			t.Fatal("a refused trigger left its agent behind")
		}
	}

	a := create(t, w.Owner, w, body)
	id := a["id"].(string)
	tools, _ := a["tools"].([]any)
	if len(tools) != 1 || tools[0].(map[string]any)["settings"].(map[string]any)["requires_user_confirmation"] != true {
		t.Fatalf("approval toggle not read back: %v", a["tools"])
	}
	triggers := w.Owner.Get(t, w.Path("/triggers/?agent_id="+id)).Expect(http.StatusOK).Array()
	if len(triggers) != 1 || triggers[0].(map[string]any)["name"] != "nightly" {
		t.Fatalf("triggers %v", triggers)
	}
	got := w.Owner.Get(t, w.Path("/agents/"+id)).Expect(http.StatusOK).Object()
	if s := got["tools"].([]any)[0].(map[string]any)["settings"].(map[string]any); s["requires_user_confirmation"] != true {
		t.Fatalf("approval toggle lost on read: %v", s)
	}
}

func TestPresetsResolveTheirCatalogSkills(t *testing.T) {
	w := h.NewWorkspace(t)
	for _, p := range w.Member.Get(t, w.Path("/agents/presets")).Expect(http.StatusOK).Array() {
		o := p.(map[string]any)
		if o["id"] != suitePresetItem {
			continue
		}
		skills := o["skills"].([]any)
		if len(skills) != 1 || skills[0].(map[string]any)["id"] != suiteSkillItem || o["instruction"] != "Help the suite" {
			t.Fatalf("preset %v", o)
		}
		if u := o["unavailable_skills"].([]any); len(u) != 1 || u[0] != "no-such-skill" {
			t.Fatalf("unavailable %v", u)
		}
		return
	}
	t.Fatal("the seeded preset is not listed")
}

func TestInstallACatalogAgentOnce(t *testing.T) {
	w := h.NewWorkspace(t)
	a := w.Member.Post(t, w.Path("/agents/suite-preset/install"), nil).Expect(http.StatusOK).Object()
	if a["registry_item_id"] != suitePresetItem || a["model_id"] != nil {
		t.Fatalf("fork %v", a)
	}
	again := w.Member.Post(t, w.Path("/agents/"+suitePresetItem+"/install"), nil).Expect(http.StatusOK).Object()
	if again["id"] != a["id"] {
		t.Fatalf("a second install made another agent: %v vs %v", again["id"], a["id"])
	}
	w.Member.Get(t, w.Path("/agents/"+a["id"].(string))).Expect(http.StatusOK)
}

func TestInstallACatalogSkill(t *testing.T) {
	w := h.NewWorkspace(t)
	sk := w.Member.Post(t, w.Path("/skills/"+suiteSkillItem+"/install"), nil).Expect(http.StatusOK).Object()
	if sk["registry_item_id"] != suiteSkillItem || sk["name"] != "suite-helper" {
		t.Fatalf("skill %v", sk)
	}
	content := w.Member.Get(t, w.Path("/skills/"+sk["id"].(string)+"/content")).Expect(http.StatusOK).Object()
	if c, _ := content["content"].(string); !strings.Contains(c, "PELICAN") {
		t.Fatalf("content %v", content)
	}
	again := w.Member.Post(t, w.Path("/skills/"+suiteSkillItem+"/install"), nil).Expect(http.StatusOK).Object()
	if again["id"] != sk["id"] {
		t.Fatal("a second install made another skill")
	}
}

func TestInstallOfAnArchivedAgentNeedsItsDelete(t *testing.T) {
	w := h.NewWorkspace(t)
	id := create(t, w.Owner, w, map[string]any{"name": "Kept Away", "tools": []any{}})["id"].(string)
	w.Owner.Delete(t, w.Path("/agents/"+id)).Expect(http.StatusOK)
	for _, ident := range []string{id, "kept-away"} {
		w.Member.Post(t, w.Path("/agents/"+ident+"/install"), nil).Expect(http.StatusForbidden)
	}
	if got := w.Owner.Get(t, w.Path("/agents/"+id)).Expect(http.StatusOK).Object(); got["status"] != "archived" {
		t.Fatalf("a member's install restored the agent: %v", got["status"])
	}
	if got := w.Owner.Post(t, w.Path("/agents/"+id+"/install"), nil).Expect(http.StatusOK).Object(); got["status"] != "active" {
		t.Fatalf("the owner's install: %v", got["status"])
	}
}
