//go:build suite

package agents

import (
	"net/http"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func client(id any, name, kind string, over map[string]any) map[string]any {
	c := map[string]any{
		"id": id, "workspace_id": h.AnyString, "created_by": h.AnyString, "name": name, "description": nil, "kind": kind,
		"models": nil, "default_model": nil, "allow_domains": []any{}, "sandbox": true,
		"skills": []any{}, "mcp_instances": []any{}, "openapi_connections": []any{}, "platform_toolsets": []any{},
		"mcp_endpoint_url": h.Pattern(`/mcp/clients/[0-9a-f-]{36}$`), "online": false, "has_runner": kind == "codex" || kind == "claude",
	}
	for k, v := range over {
		c[k] = v
	}
	return c
}

func TestClientCreateReadUpdateDelete(t *testing.T) {
	w := h.NewWorkspace(t)
	made := w.Owner.Post(t, w.Path("/clients/"), map[string]any{"name": "  Codex  ", "kind": "codex"}).Expect(http.StatusCreated).
		Match(client(h.AnyUUID, "Codex", "codex", nil)).Object()
	id := made["id"].(string)
	w.Owner.Get(t, w.Path("/clients/")).Expect(http.StatusOK).Match([]any{client(id, "Codex", "codex", nil)})
	w.Owner.Patch(t, w.Path("/clients/"+id), map[string]any{"allow_domains": []any{"pypi.org"}, "sandbox": false}).Expect(http.StatusOK).
		Match(client(id, "Codex", "codex", map[string]any{"allow_domains": []any{"pypi.org"}, "sandbox": false}))
	w.Owner.Patch(t, w.Path("/clients/"+id), map[string]any{"name": nil}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Patch(t, w.Path("/clients/"+id), map[string]any{"allow_domains": []any{"bad host"}}).Expect(http.StatusUnprocessableEntity)
	w.Outsider.Get(t, w.Path("/clients/"+id)).Expect(http.StatusForbidden, http.StatusNotFound)
	w.Owner.Get(t, w.Path("/clients/not-a-uuid")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Delete(t, w.Path("/clients/"+id)).Expect(http.StatusNoContent)
	w.Owner.Get(t, w.Path("/clients/"+id)).Expect(http.StatusNotFound, http.StatusForbidden)
}

func TestClientPlatformToolsets(t *testing.T) {
	w := h.NewWorkspace(t)
	all := w.Owner.Get(t, w.Path("/clients/platform-toolsets")).Expect(http.StatusOK).Array()
	if len(all) != 22 || all[0].(map[string]any)["name"] != "agentarea/agents" {
		t.Fatalf("catalogue %v", all)
	}
	id := w.Owner.Post(t, w.Path("/clients/"), map[string]any{"name": "H"}).Expect(http.StatusCreated).Object()["id"].(string)
	w.Owner.Post(t, w.Path("/clients/"+id+"/platform-toolsets"), map[string]any{"name": "runs", "disabled_methods": []any{"cancel"}}).Expect(http.StatusNoContent)
	w.Owner.Get(t, w.Path("/clients/"+id)).Expect(http.StatusOK).Match(client(id, "H", "harness", map[string]any{
		"platform_toolsets": []any{map[string]any{"name": "agentarea/runs", "disabled_methods": []any{"cancel"}}},
	}))
	w.Owner.Post(t, w.Path("/clients/"+id+"/platform-toolsets"), map[string]any{"name": "nope"}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Delete(t, w.Path("/clients/"+id+"/platform-toolsets/agentarea/runs")).Expect(http.StatusNoContent)
	w.Owner.Get(t, w.Path("/clients/"+id)).Expect(http.StatusOK).Match(client(id, "H", "harness", nil))
}

func TestClientHarnessAgentIsMadeOnce(t *testing.T) {
	w := h.NewWorkspace(t)
	id := w.Owner.Post(t, w.Path("/clients/"), map[string]any{"name": "Claude", "kind": "claude"}).Expect(http.StatusCreated).Object()["id"].(string)
	first := w.Owner.Post(t, w.Path("/clients/"+id+"/agent"), nil).Expect(http.StatusOK).Object()
	if first["name"] != "Claude" || first["client_id"] != id {
		t.Fatalf("harness agent %v", first)
	}
	w.Owner.Post(t, w.Path("/clients/"+id+"/agent"), nil).Expect(http.StatusOK).Match(first)
	w.Owner.Delete(t, w.Path("/clients/"+id)).Expect(http.StatusConflict)
}
