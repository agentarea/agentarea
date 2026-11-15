//go:build suite

// Package agents pins /v1/workspaces/{workspace}/agents and skill-collections
// (.omc/research/go-migration/dossiers/agents.md, sections 2.1 and 2.4).
package agents

import (
	"net/http"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

func agent(w *h.Workspace, id any, slug, name, status string, over map[string]any) map[string]any {
	a := map[string]any{
		"id": id, "slug": slug, "name": name, "status": status, "description": "", "instruction": "",
		"model_id": nil, "client_id": nil, "client": nil, "tools": nil, "planning": nil, "a2ui_enabled": nil,
		"reasoning_effort": nil, "reasoning_max_tokens": nil, "answer_check": nil, "agent_type": "stateless",
		"skills": nil, "is_catalog": false, "registry_item_id": nil, "update_available": false,
		"a2a_url": h.Pattern(`^http://[0-9a-f-]{36}\.a2a\.localhost:8000$`),
	}
	for k, v := range over {
		a[k] = v
	}
	return a
}

func create(t *testing.T, c *h.Client, w *h.Workspace, body map[string]any) map[string]any {
	t.Helper()
	return c.Post(t, w.Path("/agents/"), body).Expect(http.StatusOK).Object()
}

func notFound() map[string]any {
	return h.Problem(http.StatusNotFound, "http_error", "Agent not found")
}

func TestCreateAnswers200AndReadsBack(t *testing.T) {
	w := h.NewWorkspace(t)
	resp := w.Owner.Post(t, w.Path("/agents/"), map[string]any{"name": "  Helper  ", "tools": []any{}}).Expect(http.StatusOK)
	if ct := resp.ContentType(); ct != "application/json" {
		t.Fatalf("content-type %q", ct)
	}
	made := resp.Match(agent(w, h.AnyUUID, "helper", "Helper", "active", nil)).Object()
	id := made["id"].(string)

	want := agent(w, id, "helper", "Helper", "active", nil)
	w.Owner.Get(t, w.Path("/agents/"+id)).Expect(http.StatusOK).Match(want)
	w.Owner.Get(t, w.Path("/agents/helper")).Expect(http.StatusOK).Match(want)
	w.Owner.Get(t, w.Path("/agents/")).Expect(http.StatusOK).Match([]any{want})
	w.Owner.Get(t, w.Path("/agents")).Expect(http.StatusOK).Match([]any{want})
}

func TestSlugsCollideWithSuffix(t *testing.T) {
	w := h.NewWorkspace(t)
	first := create(t, w.Owner, w, map[string]any{"name": "My Agent!", "tools": []any{}})
	second := create(t, w.Owner, w, map[string]any{"name": "My Agent", "tools": []any{}})
	if first["slug"] != "my-agent" || second["slug"] != "my-agent-2" {
		t.Fatalf("slugs %v %v", first["slug"], second["slug"])
	}
	allNonAscii := create(t, w.Owner, w, map[string]any{"name": "Привет", "tools": []any{}})
	if allNonAscii["slug"] != "item" {
		t.Fatalf("slug %v", allNonAscii["slug"])
	}
}

func TestToolsAreNormalisedLikeThePydanticUnion(t *testing.T) {
	w := h.NewWorkspace(t)
	made := create(t, w.Owner, w, map[string]any{"name": "Delegator", "tools": []any{
		map[string]any{"type": "agent", "name": " Remote ", "settings": map[string]any{
			"a2a_url": "https://example.com/agent/", "junk": 1, "requires_user_confirmation": false}},
	}})
	want := []any{map[string]any{"name": "Remote", "type": "agent", "settings": map[string]any{
		"requires_user_confirmation": nil, "description_override": nil, "agent_id": nil,
		"a2a_url": "https://example.com/agent", "auth_secret_name": nil}}}
	if err := h.Compare(made["tools"], want); err != nil {
		t.Fatal(err)
	}
	id := made["id"].(string)
	w.Owner.Get(t, w.Path("/agents/"+id)).Expect(http.StatusOK).Match(
		agent(w, id, "delegator", "Delegator", "active", map[string]any{"tools": want}))
}

func TestValidationErrorsAre422(t *testing.T) {
	w := h.NewWorkspace(t)
	for name, body := range map[string]map[string]any{
		"tools required":     {"name": "x"},
		"name required":      {"tools": []any{}},
		"empty name":         {"name": "   ", "tools": []any{}},
		"unknown field":      {"name": "x", "tools": []any{}, "nope": 1},
		"bad tool type":      {"name": "x", "tools": []any{map[string]any{"type": "wat", "name": "a"}}},
		"both reasoning":     {"name": "x", "tools": []any{}, "reasoning_effort": "low", "reasoning_max_tokens": 5},
		"bad effort":         {"name": "x", "tools": []any{}, "reasoning_effort": "Not A Level"},
		"bad agent type":     {"name": "x", "tools": []any{}, "agent_type": "wat"},
		"description length": {"name": "x", "tools": []any{}, "description": strings.Repeat("a", 1001)},
	} {
		t.Run(name, func(t *testing.T) {
			r := w.Owner.Post(t, w.Path("/agents/"), body).Expect(http.StatusUnprocessableEntity).Object()
			if r["code"] != "validation_error" {
				t.Fatalf("code %v", r["code"])
			}
		})
	}
	w.Owner.Post(t, w.Path("/agents/"), map[string]any{"name": "x", "tools": []any{}, "model_id": "not-a-uuid"}).
		Expect(http.StatusBadRequest).Match(h.Problem(http.StatusBadRequest, "invalid_model_id",
		"Invalid model_id 'not-a-uuid': expected the UUID of a model instance. List available instances via GET /v1/model-instances."))
}

func TestPatchChangesOnlyWhatIsSent(t *testing.T) {
	w := h.NewWorkspace(t)
	made := create(t, w.Owner, w, map[string]any{"name": "Editor", "description": "d", "instruction": "i",
		"tools": []any{}, "planning": true})
	id := made["id"].(string)

	w.Owner.Patch(t, w.Path("/agents/"+id), map[string]any{"instruction": "be brief", "description": nil}).
		Expect(http.StatusOK).Match(agent(w, id, "editor", "Editor", "active", map[string]any{
		"description": nil, "instruction": "be brief", "planning": true}))
	w.Owner.Patch(t, w.Path("/agents/editor"), map[string]any{"name": "Renamed"}).
		Expect(http.StatusOK).Match(agent(w, id, "editor", "Renamed", "active", map[string]any{
		"description": nil, "instruction": "be brief", "planning": true}))

	w.Owner.Patch(t, w.Path("/agents/"+id), map[string]any{"name": nil}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Patch(t, w.Path("/agents/"+id), map[string]any{"nope": 1}).Expect(http.StatusUnprocessableEntity)

	w.Owner.Patch(t, w.Path("/agents/"+id), map[string]any{"reasoning_effort": "low"}).Expect(http.StatusOK)
	w.Owner.Patch(t, w.Path("/agents/"+id), map[string]any{"reasoning_max_tokens": 100}).
		Expect(http.StatusUnprocessableEntity).
		Match(h.Problem(http.StatusUnprocessableEntity, "http_error", "set reasoning_effort or reasoning_max_tokens, not both"))
	w.Owner.Patch(t, w.Path("/agents/"+id), map[string]any{"reasoning_effort": nil, "reasoning_max_tokens": 100}).
		Expect(http.StatusOK)
}

func TestArchiveHidesFromListAndRestoreBringsBack(t *testing.T) {
	w := h.NewWorkspace(t)
	made := create(t, w.Owner, w, map[string]any{"name": "Gone", "tools": []any{}})
	id := made["id"].(string)

	w.Owner.Delete(t, w.Path("/agents/"+id)).Expect(http.StatusOK).Match(map[string]any{"status": "success"})
	w.Owner.Delete(t, w.Path("/agents/"+id)).Expect(http.StatusOK).Match(map[string]any{"status": "success"})
	w.Owner.Get(t, w.Path("/agents/")).Expect(http.StatusOK).Match([]any{})
	w.Owner.Get(t, w.Path("/agents/"+id)).Expect(http.StatusOK).Match(agent(w, id, "gone", "Gone", "archived", nil))

	archived := h.Problem(http.StatusConflict, "http_error",
		"Agent "+id+" is archived. Restore it before using or editing it.")
	w.Owner.Patch(t, w.Path("/agents/"+id), map[string]any{"name": "Nope"}).Expect(http.StatusConflict).Match(archived)

	w.Owner.Post(t, w.Path("/agents/"+id+"/restore"), nil).Expect(http.StatusOK).
		Match(agent(w, id, "gone", "Gone", "active", nil))
	listed(t, w.Owner, w, id)
}

func TestAccessMatrix(t *testing.T) {
	w := h.NewWorkspace(t)
	id := create(t, w.Owner, w, map[string]any{"name": "Private", "tools": []any{}})["id"].(string)

	// In its own workspace a foreign id is unknown; the PDP answers 403 where it checks first.
	w.Outsider.Get(t, w.OutsiderPath("/agents/"+id)).Expect(http.StatusNotFound).Match(notFound())
	w.Outsider.Patch(t, w.OutsiderPath("/agents/"+id), map[string]any{"name": "x"}).Expect(http.StatusForbidden).
		Match(h.Problem(http.StatusForbidden, "http_error", "Permission denied"))
	w.Outsider.Delete(t, w.OutsiderPath("/agents/"+id)).Expect(http.StatusForbidden)
	w.Outsider.Post(t, w.OutsiderPath("/agents/"+id+"/restore"), nil).Expect(http.StatusForbidden)
	w.Outsider.Get(t, w.OutsiderPath("/agents/")).Expect(http.StatusOK).Match([]any{})

	w.Outsider.Get(t, w.Path("/agents/")).Expect(http.StatusForbidden).
		Match(h.Problem(http.StatusForbidden, "http_error", "User is not a member of the requested workspace"))
	w.Anonymous.Get(t, w.Path("/agents/")).Expect(http.StatusUnauthorized).
		Match(h.Problem(http.StatusUnauthorized, "http_error", "Missing authentication credentials"))

	w.Owner.Get(t, w.Path("/agents/no-such-slug")).Expect(http.StatusNotFound).Match(notFound())
	w.Member.Get(t, w.Path("/agents/"+id)).Expect(http.StatusOK)
	listed(t, w.Member, w, id)

	key := w.APIKey(t)
	key.Get(t, w.Path("/agents/"+id)).Expect(http.StatusOK)
}

func TestSkillCollections(t *testing.T) {
	w := h.NewWorkspace(t)
	c := w.Owner.Post(t, w.Path("/skill-collections/"), map[string]any{"name": "Docs"}).Expect(http.StatusCreated).
		Match(map[string]any{"id": h.AnyUUID, "name": "Docs", "description": nil, "skill_count": 0}).Object()
	id := c["id"].(string)

	w.Owner.Get(t, w.Path("/skill-collections/")).Expect(http.StatusOK).
		Match([]any{map[string]any{"id": id, "name": "Docs", "description": nil, "skill_count": 0}})
	w.Owner.Get(t, w.Path("/skill-collections/"+id)).Expect(http.StatusOK).
		Match(map[string]any{"id": id, "name": "Docs", "description": nil, "skills": []any{}})

	w.Owner.Put(t, w.Path("/skill-collections/"+id), map[string]any{"description": "all docs"}).Expect(http.StatusOK).
		Match(map[string]any{"id": id, "name": "Docs", "description": "all docs", "skill_count": 0})
	w.Owner.Put(t, w.Path("/skill-collections/"+id), map[string]any{"name": "Docs 2"}).Expect(http.StatusOK).
		Match(map[string]any{"id": id, "name": "Docs 2", "description": "all docs", "skill_count": 0})
	w.Owner.Put(t, w.Path("/skill-collections/"+id), map[string]any{"description": nil}).Expect(http.StatusOK).
		Match(map[string]any{"id": id, "name": "Docs 2", "description": nil, "skill_count": 0})

	missing := "00000000-0000-4000-8000-000000000001"
	w.Owner.Post(t, w.Path("/skill-collections/"+id+"/skills"), map[string]any{"skill_id": missing}).
		Expect(http.StatusNotFound).Match(h.Problem(http.StatusNotFound, "http_error", "Skill not found"))
	w.Owner.Post(t, w.Path("/skill-collections/"+id+"/skills"), map[string]any{}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Delete(t, w.Path("/skill-collections/"+id+"/skills/"+missing)).Expect(http.StatusNoContent)

	w.Outsider.Put(t, w.OutsiderPath("/skill-collections/"+id), map[string]any{"name": "x"}).Expect(http.StatusForbidden)
	w.Outsider.Delete(t, w.OutsiderPath("/skill-collections/"+id)).Expect(http.StatusForbidden)
	w.Outsider.Get(t, w.OutsiderPath("/skill-collections/"+id)).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Collection not found"))

	w.Owner.Delete(t, w.Path("/skill-collections/"+id)).Expect(http.StatusNoContent)
	w.Owner.Delete(t, w.Path("/skill-collections/"+id)).Expect(http.StatusForbidden)
	w.Owner.Get(t, w.Path("/skill-collections/"+id)).Expect(http.StatusNotFound)
	w.Owner.Post(t, w.Path("/skill-collections/"), map[string]any{"name": ""}).Expect(http.StatusUnprocessableEntity)
}

func listed(t *testing.T, c *h.Client, w *h.Workspace, id string) {
	t.Helper()
	for _, a := range c.Get(t, w.Path("/agents/")).Expect(http.StatusOK).Array() {
		if a.(map[string]any)["id"] == id {
			return
		}
	}
	t.Fatalf("%s: agent %s is not listed", c.Name, id)
}
