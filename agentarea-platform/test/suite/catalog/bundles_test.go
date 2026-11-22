//go:build suite

package catalog

import (
	"net/http"
	"reflect"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

// The suite catalog's provider and chat model (deploy/suite seed).
const (
	suiteProvider = "5e1f0000-0000-4000-8000-000000000001"
	suiteChat     = "5e1f0000-0000-4000-8000-000000000002"
)

// suiteModel is a chat model instance in w: a bundle's agent must name one.
func suiteModel(t *testing.T, w *h.Workspace) string {
	t.Helper()
	cfg := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": suiteProvider, "name": "Suite", "api_key": "sk-suite", "endpoint_url": "http://127.0.0.1:9",
	}).Expect(http.StatusOK).Object()
	return w.Owner.Post(t, w.Path("/model-instances/"), map[string]any{
		"provider_config_id": cfg["id"], "model_spec_id": suiteChat, "name": "Suite chat",
	}).Expect(http.StatusOK).Object()["id"].(string)
}

func folder(model, instruction string, extra map[string]any) map[string]any {
	files := map[string]any{
		"agent.yaml":            "name: suite-deploy\ndescription: Deployed by the suite\nmodel: " + model + "\n",
		"instructions.md":       instruction,
		"skills/notes/SKILL.md": "---\nname: notes\ndescription: Takes notes\n---\n# Notes\n",
		"schedules/daily.md":    "---\ncron: '0 9 * * *'\ntimezone: UTC\nenabled: false\n---\nSummarize the day.\n",
	}
	for k, v := range extra {
		files[k] = v
	}
	return files
}

func analyze(t *testing.T, c *h.Client, w *h.Workspace, body map[string]any) map[string]any {
	t.Helper()
	return c.Post(t, w.Path("/bundles/analyze"), body).Expect(http.StatusOK).Object()
}

func install(c *h.Client, t *testing.T, w *h.Workspace, preview map[string]any, setup map[string]any) *h.Response {
	t.Helper()
	if setup == nil {
		setup = map[string]any{}
	}
	body := map[string]any{"bundle": preview["bundle"], "setup_values": setup, "plan_digest": preview["plan_digest"]}
	if into, ok := preview["install"].(map[string]any); ok {
		body["install_id"] = into["id"]
	}
	return c.Post(t, w.Path("/bundles/install"), body)
}

func statuses(t *testing.T, entities any, field string) map[string]string {
	t.Helper()
	out := map[string]string{}
	for _, e := range entities.([]any) {
		m := e.(map[string]any)
		out[m["kind"].(string)+":"+m["key"].(string)] = m[field].(string)
	}
	return out
}

func TestBundleAnalyzeRefusesBadRequests(t *testing.T) {
	w := h.NewWorkspace(t)
	exactlyOne := "Value error, provide exactly one of 'source', 'source_url', 'files' or 'bundle'"
	got := w.Member.Post(t, w.Path("/bundles/analyze"), map[string]any{}).Expect(http.StatusUnprocessableEntity).Object()
	if errs := got["errors"].([]any); len(errs) != 1 || errs[0].(map[string]any)["msg"] != exactlyOne {
		t.Fatalf("errors = %v", got["errors"])
	}
	w.Member.Post(t, w.Path("/bundles/analyze"), map[string]any{"source": "x", "source_url": "https://example.com/b.yaml"}).
		Expect(http.StatusUnprocessableEntity)
	w.Member.Post(t, w.Path("/bundles/analyze"), map[string]any{"files": map[string]any{"../agent.yaml": "name: x"}}).
		Expect(http.StatusUnprocessableEntity)
	w.Member.Post(t, w.Path("/bundles/analyze"), map[string]any{"source": "- just\n- a list\n"}).
		Expect(http.StatusUnprocessableEntity).Match(h.Problem(http.StatusUnprocessableEntity, "http_error", "package must be a mapping at the top level"))
	w.Member.Post(t, w.Path("/bundles/analyze"), map[string]any{"files": map[string]any{"README.md": "# hi"}}).
		Expect(http.StatusUnprocessableEntity)
	w.Member.Post(t, w.Path("/bundles/analyze"), map[string]any{"source_url": "http://127.0.0.1/bundle.yaml"}).
		Expect(http.StatusBadRequest)
	w.Member.Post(t, w.Path("/bundles/install"), map[string]any{"plan_digest": ""}).Expect(http.StatusUnprocessableEntity)
}

func TestBundleDeployCreatesThenRedeploysInPlace(t *testing.T) {
	w := h.NewWorkspace(t)
	model := suiteModel(t, w)
	first := analyze(t, w.Owner, w, map[string]any{"files": folder(model, "Be thorough.\n", nil)})
	if first["installable"] != true || first["plan_digest"] == nil {
		t.Fatalf("preview = %v", first)
	}
	want := map[string]string{"skill:notes": "will_create", "agent:agent": "will_create", "automation:daily": "will_create"}
	if got := statuses(t, first["entities"], "status"); !reflect.DeepEqual(got, want) {
		t.Fatalf("plan = %v, want %v", got, want)
	}

	result := install(w.Owner, t, w, first, nil).Expect(http.StatusOK).Object()
	if id, _ := result["installed_bundle_id"].(string); id == "" || result["bundle_name"] != "suite-deploy" {
		t.Fatalf("result = %v", result)
	}
	created := map[string]string{"skill:notes": "created", "agent:agent": "created", "automation:daily": "created"}
	if got := statuses(t, result["entities"], "action"); !reflect.DeepEqual(got, created) {
		t.Fatalf("actions = %v", got)
	}
	var agentID string
	for _, e := range result["entities"].([]any) {
		if m := e.(map[string]any); m["kind"] == "agent" {
			agentID = m["id"].(string)
		}
	}
	agent := w.Owner.Get(t, w.Path("/agents/"+agentID)).Expect(http.StatusOK).Object()
	if agent["instruction"] != "Be thorough.\n" || agent["name"] != "suite-deploy" {
		t.Fatalf("agent = %v", agent)
	}

	installID := result["install_id"]
	if installID != result["installed_bundle_id"] {
		t.Fatalf("install_id = %v, installed_bundle_id = %v", installID, result["installed_bundle_id"])
	}
	taken := analyze(t, w.Owner, w, map[string]any{"files": folder(model, "Be thorough.\n", nil)})
	if taken["installable"] != false || taken["plan_digest"] != nil || taken["existing_install"].(map[string]any)["id"] != installID {
		t.Fatalf("plan over an installed name = %v", taken)
	}
	exists := false
	for _, i := range taken["issues"].([]any) {
		exists = exists || i.(map[string]any)["code"] == "bundle_exists"
	}
	if !exists {
		t.Fatalf("issues = %v", taken["issues"])
	}

	again := analyze(t, w.Owner, w, map[string]any{"files": folder(model, "Be thorough.\n", nil), "into": installID})
	unchanged := map[string]string{"skill:notes": "unchanged", "agent:agent": "unchanged", "automation:daily": "unchanged"}
	if got := statuses(t, again["entities"], "status"); !reflect.DeepEqual(got, unchanged) {
		t.Fatalf("replan = %v", got)
	}

	changed := analyze(t, w.Owner, w, map[string]any{"files": folder(model, "Be brief.\n", nil), "into": installID})
	if got := statuses(t, changed["entities"], "status"); got["agent:agent"] != "will_update" {
		t.Fatalf("change plan = %v", got)
	}
	stale := map[string]any{"bundle": changed["bundle"], "setup_values": map[string]any{}, "plan_digest": first["plan_digest"], "install_id": installID}
	w.Owner.Post(t, w.Path("/bundles/install"), stale).Expect(http.StatusConflict).Match(map[string]any{
		"type": "about:blank", "title": "Conflict", "status": 409, "code": "bundle_plan_changed",
		"detail": "the deploy plan changed since it was shown; analyze the bundle again and review the new plan", "issues": []any{},
	})
	updated := install(w.Owner, t, w, changed, nil).Expect(http.StatusOK).Object()
	if got := statuses(t, updated["entities"], "action"); got["agent:agent"] != "updated" || got["skill:notes"] != "unchanged" {
		t.Fatalf("redeploy actions = %v", got)
	}
	if updated["installed_bundle_id"] != result["installed_bundle_id"] {
		t.Fatalf("redeploy recorded a second bundle: %v vs %v", updated["installed_bundle_id"], result["installed_bundle_id"])
	}
	if got := w.Owner.Get(t, w.Path("/agents/"+agentID)).Expect(http.StatusOK).Object(); got["instruction"] != "Be brief.\n" {
		t.Fatalf("agent after redeploy = %v", got["instruction"])
	}
}

func TestBundleInstallRefusesMissingRequiredSetup(t *testing.T) {
	w := h.NewWorkspace(t)
	model := suiteModel(t, w)
	files := folder(model, "Use the token.\n", map[string]any{
		"agent.yaml": "name: suite-setup\nsetup:\n  - {key: token, label: Token, type: secret, required: true}\n",
	})
	preview := analyze(t, w.Owner, w, map[string]any{"files": files})
	if preview["installable"] != false {
		t.Fatalf("preview = %v", preview)
	}
	got := install(w.Owner, t, w, preview, nil).Expect(http.StatusUnprocessableEntity).Object()
	if got["code"] != "bundle_invalid" || !strings.HasPrefix(got["detail"].(string), "package is not installable: ") {
		t.Fatalf("problem = %v", got)
	}
	issues := got["issues"].([]any)
	if len(issues) == 0 || issues[0].(map[string]any)["severity"] != "block" {
		t.Fatalf("issues = %v", issues)
	}
}

func TestBundleWithAPolicyIsForAdmins(t *testing.T) {
	w := h.NewWorkspace(t)
	model := suiteModel(t, w)
	files := folder(model, "Never email.\n", map[string]any{
		"agent.yaml":             "name: suite-policy\nmodel: " + model + "\n",
		"policies/no_email.yaml": "target: 'tool:send_email'\neffect: deny\n",
	})
	preview := analyze(t, w.Member, w, map[string]any{"files": files})
	install(w.Member, t, w, preview, nil).Expect(http.StatusForbidden)
	result := install(w.Owner, t, w, preview, nil).Expect(http.StatusOK).Object()
	if got := statuses(t, result["entities"], "action"); got["policy:no_email"] != "created" {
		t.Fatalf("actions = %v", got)
	}
}
