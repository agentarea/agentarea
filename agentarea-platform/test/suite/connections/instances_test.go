//go:build suite

package connections

import (
	"encoding/json"
	"net/http"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

// urlInstance creates a URL MCP server and its instance in one call (with-spec).
func urlInstance(t *testing.T, c *h.Client, w *h.Workspace, name string, headers map[string]any) map[string]any {
	t.Helper()
	spec := map[string]any{"type": "url", "endpoint_url": unresolvable}
	if headers != nil {
		spec["headers"] = headers
	}
	return c.Post(t, w.Path("/mcp-server-instances/with-spec"), map[string]any{
		"server": map[string]any{
			"name": name + " server", "description": "suite server", "remote_url": unresolvable,
			"env_schema": []any{map[string]any{"name": "X-Region", "is_secret": false}},
		},
		"instance": map[string]any{"name": name, "json_spec": spec},
	}).Expect(http.StatusCreated).Object()
}

func TestURLInstanceCreateMasksSecretsAndRecordsAFailedVerification(t *testing.T) {
	w := h.NewWorkspace(t)
	inst := urlInstance(t, w.Owner, w, "Search", map[string]any{"X-Api-Key": "plain-secret", "X-Region": "eu"})
	id := str(t, inst, "id")

	if strings.Contains(stringify(inst), "plain-secret") {
		t.Fatalf("the secret header is in the create response: %v", inst)
	}
	if inst["transport"] != "url" || inst["personal"] != true || inst["is_owner"] != true || inst["managed_by"] != nil {
		t.Fatalf("create %v", inst)
	}
	headers := obj(t, obj(t, inst, "json_spec"), "headers")
	if headers["X-Api-Key"] != "******" || headers["X-Region"] != "eu" {
		t.Fatalf("headers %v", headers)
	}
	v := obj(t, inst, "verification")
	if v["schema_version"] == nil || (v["status"] != "failed" && v["status"] != "in_progress") {
		t.Fatalf("verification %v", v)
	}

	got := w.Owner.Get(t, w.Path("/mcp-server-instances/"+id)).Expect(http.StatusOK).Object()
	if obj(t, obj(t, got, "json_spec"), "headers")["X-Api-Key"] != "******" {
		t.Fatalf("get shows the secret: %v", got["json_spec"])
	}
	if strings.Contains(stringify(got), "plain-secret") {
		t.Fatal("get carries the secret value")
	}
	list := w.Owner.Get(t, w.Path("/mcp-server-instances/")).Expect(http.StatusOK).Array()
	found := false
	for _, e := range list {
		if m, ok := e.(map[string]any); ok && m["id"] == id {
			found = true
		}
	}
	if !found {
		t.Fatalf("list lacks %s", id)
	}
}

func TestInstancePatchSharingAndDelete(t *testing.T) {
	w := h.NewWorkspace(t)
	id := str(t, urlInstance(t, w.Owner, w, "Docs", map[string]any{"X-Api-Key": "k1"}), "id")
	path := w.Path("/mcp-server-instances/" + id)

	patched := w.Owner.Patch(t, path, map[string]any{"name": "Docs v2", "description": "renamed"}).Expect(http.StatusOK).Object()
	if patched["name"] != "Docs v2" || patched["description"] != "renamed" {
		t.Fatalf("patch %v", patched)
	}
	w.Owner.Patch(t, path, map[string]any{"name": nil}).Expect(http.StatusUnprocessableEntity)

	shared := w.Owner.Put(t, path+"/sharing", map[string]any{"shared": true}).Expect(http.StatusOK).Object()
	if shared["personal"] != false {
		t.Fatalf("sharing %v", shared)
	}
	w.Owner.Put(t, path+"/sharing", map[string]any{}).Expect(http.StatusUnprocessableEntity)
	personal := w.Owner.Put(t, path+"/sharing", map[string]any{"shared": false}).Expect(http.StatusOK).Object()
	if personal["personal"] != true {
		t.Fatalf("unsharing %v", personal)
	}

	w.Owner.Delete(t, path).Expect(http.StatusOK).Match(map[string]any{"status": "success"})
	w.Owner.Get(t, path).Expect(http.StatusNotFound)
	w.Owner.Delete(t, path).Expect(http.StatusNotFound, http.StatusForbidden)
}

func TestInstanceMissingAndForeignAre404(t *testing.T) {
	w := h.NewWorkspace(t)
	id := str(t, urlInstance(t, w.Owner, w, "Mine", nil), "id")
	w.Owner.Get(t, w.Path("/mcp-server-instances/"+missing)).Expect(http.StatusNotFound)
	w.Outsider.Get(t, w.OutsiderPath("/mcp-server-instances/"+id)).Expect(http.StatusNotFound)
	w.Outsider.Get(t, w.Path("/mcp-server-instances/")).Expect(http.StatusForbidden, http.StatusNotFound)
	w.Owner.Get(t, w.Path("/mcp-server-instances/not-a-uuid")).Expect(http.StatusUnprocessableEntity)
}

func TestInstanceAdminRoutes(t *testing.T) {
	w := h.NewWorkspace(t)
	id := str(t, urlInstance(t, w.Owner, w, "Env", map[string]any{"X-Api-Key": "k"}), "id")
	path := w.Path("/mcp-server-instances/" + id)

	env := w.Owner.Get(t, path+"/environment").Expect(http.StatusOK).Object()
	if env["instance_id"] != id || env["message"] == nil {
		t.Fatalf("environment %v", env)
	}
	if strings.Contains(stringify(env), "k\"") {
		t.Fatalf("environment shows a value: %v", env)
	}
	w.Member.Get(t, path+"/environment").Expect(http.StatusForbidden)
	w.Owner.Get(t, path+"/oauth-links").Expect(http.StatusOK).Match([]any{})
	w.Member.Get(t, path+"/oauth-links").Expect(http.StatusForbidden)

	w.Owner.Post(t, path+"/oauth-link", map[string]any{}).Expect(http.StatusNotImplemented)
	w.Owner.Post(t, path+"/test-auth", nil).Expect(http.StatusBadRequest)
}

func TestInstanceRefusesAPrivateEndpoint(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Owner.Post(t, w.Path("/mcp-server-instances/with-spec"), map[string]any{
		"server":   map[string]any{"name": "Local", "description": "d", "remote_url": "http://169.254.169.254/mcp"},
		"instance": map[string]any{"name": "Local", "json_spec": map[string]any{"type": "url", "endpoint_url": "http://169.254.169.254/mcp"}},
	}).Expect(http.StatusUnprocessableEntity).Match(map[string]any{
		"type": "about:blank", "title": "Unprocessable Content", "status": json.Number("422"), "code": "http_error",
		"detail": "Endpoint URL is not an allowed address", "errors": []any{"Endpoint URL is not an allowed address"},
	})
}

func TestInstanceCreateValidation(t *testing.T) {
	w := h.NewWorkspace(t)
	base := w.Path("/mcp-server-instances/")
	w.Owner.Post(t, base, map[string]any{"name": "x"}).Expect(http.StatusUnprocessableEntity)
	if d := w.Owner.Post(t, base, map[string]any{"name": "x", "server_spec_id": missing, "json_spec": map[string]any{}}).
		Expect(http.StatusUnprocessableEntity).Object()["detail"]; d != "server_spec_id '"+missing+"' was not found" {
		t.Fatalf("missing spec detail %v", d)
	}
	w.Owner.Post(t, base+"with-spec", map[string]any{"server": map[string]any{"name": "s", "description": "d"}}).
		Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, base+"with-spec", map[string]any{
		"server": map[string]any{"name": "s", "description": "d", "remote_url": unresolvable}, "instance": map[string]any{"name": "   "},
	}).Expect(http.StatusBadRequest)
}

func TestValidateEndpoints(t *testing.T) {
	w := h.NewWorkspace(t)
	base := w.Path("/mcp-server-instances/")
	w.Owner.Post(t, base+"validate", map[string]any{"type": "docker"}).Expect(http.StatusOK).
		Match(map[string]any{"valid": true, "errors": []any{}})
	w.Owner.Post(t, base+"validate", map[string]any{"type": "nope"}).Expect(http.StatusOK).
		Match(map[string]any{"valid": false, "errors": []any{"Unknown type: nope"}})
	w.Owner.Post(t, base+"validate", map[string]any{"type": "url"}).Expect(http.StatusOK).
		Match(map[string]any{"valid": false, "errors": []any{"endpoint_url is required for type=url"}})
	w.Owner.Post(t, base+"validate", map[string]any{"name": "no type"}).Expect(http.StatusUnprocessableEntity)
	unreachable := w.Owner.Post(t, base+"validate", map[string]any{"type": "url", "endpoint_url": unresolvable}).
		Expect(http.StatusOK).Object()
	if unreachable["valid"] != false {
		t.Fatalf("validate of an unresolvable endpoint %v", unreachable)
	}
	conn := w.Owner.Post(t, base+"validate-connection", map[string]any{"url": unresolvable}).Expect(http.StatusOK).Object()
	if conn["valid"] != false {
		t.Fatalf("validate-connection %v", conn)
	}
}

func TestCheckConfiguration(t *testing.T) {
	w := h.NewWorkspace(t)
	r := w.Owner.Post(t, w.Path("/mcp-server-instances/check"), map[string]any{
		"json_spec": map[string]any{"type": "url", "endpoint_url": unresolvable},
	}).Expect(http.StatusOK).Object()
	if _, ok := r["valid"].(bool); !ok {
		t.Fatalf("check %v", r)
	}
	if _, ok := r["message"].(string); !ok {
		t.Fatalf("check %v", r)
	}
}

func TestToolPolicyRoutes(t *testing.T) {
	w := h.NewWorkspace(t)
	id := str(t, urlInstance(t, w.Owner, w, "Policies", nil), "id")
	w.Owner.Get(t, w.Path("/mcp-server-instances/tool-policies")).Expect(http.StatusOK)
	w.Owner.Get(t, w.Path("/mcp-server-instances/"+id+"/tool-policies")).Expect(http.StatusOK)
	w.Owner.Get(t, w.Path("/mcp-server-instances/"+missing+"/tool-policies")).Expect(http.StatusNotFound)
}

func stringify(v any) string {
	raw, err := json.Marshal(v)
	if err != nil {
		return ""
	}
	return string(raw)
}
