//go:build suite

package connections

import (
	"net/http"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

// publicBase is a public address literal: it passes the endpoint check with
// no DNS lookup, and nothing in these tests calls it.
const publicBase = "https://1.1.1.1/v1"

// petstore is a two-operation OpenAPI document.
func petstore() map[string]any {
	return map[string]any{
		"openapi": "3.0.0",
		"info":    map[string]any{"title": "Pets", "version": "1.2.3", "description": "Pet store"},
		"servers": []any{map[string]any{"url": "https://pets.invalid/v1"}},
		"paths": map[string]any{
			"/pets": map[string]any{
				"get": map[string]any{
					"operationId": "listPets", "summary": "List pets",
					"parameters": []any{map[string]any{"name": "limit", "in": "query", "schema": map[string]any{"type": "integer"}}},
					"responses":  map[string]any{"200": map[string]any{"description": "ok"}},
				},
				"post": map[string]any{
					"operationId": "createPet", "summary": "Create a pet",
					"requestBody": map[string]any{"content": map[string]any{"application/json": map[string]any{
						"schema": map[string]any{"type": "object", "properties": map[string]any{"name": map[string]any{"type": "string"}}},
					}}},
					"responses": map[string]any{"201": map[string]any{"description": "created"}},
				},
			},
		},
	}
}

func toolNames(t *testing.T, tools any) []string {
	t.Helper()
	l, ok := tools.([]any)
	if !ok {
		t.Fatalf("tools = %#v", tools)
	}
	var out []string
	for _, e := range l {
		out = append(out, str(t, e.(map[string]any), "name"))
	}
	return out
}

func TestPreviewSpecReadsAnInlineDocument(t *testing.T) {
	w := h.NewWorkspace(t)
	p := w.Owner.Post(t, w.Path("/openapi-connections/preview-spec"), map[string]any{"spec_content": petstore()}).
		Expect(http.StatusOK).Object()
	if p["title"] != "Pets" || p["version"] != "1.2.3" || p["base_url"] != "https://pets.invalid/v1" {
		t.Fatalf("preview %v", p)
	}
	if n := len(toolNames(t, p["tools"])); n != 2 {
		t.Fatalf("preview has %d tools, want 2", n)
	}
	w.Owner.Post(t, w.Path("/openapi-connections/preview-spec"), map[string]any{"spec_content": "not an object"}).
		Expect(http.StatusUnprocessableEntity)
}

func TestOpenAPIConnectionLifecycle(t *testing.T) {
	w := h.NewWorkspace(t)
	base := w.Path("/openapi-connections/")
	c := w.Owner.Post(t, base, map[string]any{
		"name": "Pets", "base_url": publicBase, "spec_content": petstore(),
		"custom_headers": []any{map[string]any{"name": "X-Api-Key", "value": "pet-secret"}},
	}).Expect(http.StatusCreated).Object()
	id := str(t, c, "id")
	if strings.Contains(stringify(c), "pet-secret") {
		t.Fatalf("create shows the header value: %v", c)
	}
	if c["personal"] != true || c["is_owner"] != true || len(toolNames(t, c["available_tools"])) != 2 {
		t.Fatalf("create %v", c)
	}

	got := w.Owner.Get(t, base+id).Expect(http.StatusOK).Object()
	if got["name"] != "Pets" || strings.Contains(stringify(got), "pet-secret") {
		t.Fatalf("get %v", got)
	}
	listed := false
	for _, e := range w.Owner.Get(t, base).Expect(http.StatusOK).Array() {
		if e.(map[string]any)["id"] == id {
			listed = true
		}
	}
	if !listed {
		t.Fatal("list lacks the connection")
	}

	patched := w.Owner.Patch(t, base+id, map[string]any{"name": "Pets v2", "description": "renamed"}).Expect(http.StatusOK).Object()
	if patched["name"] != "Pets v2" || patched["description"] != "renamed" {
		t.Fatalf("patch %v", patched)
	}
	w.Owner.Patch(t, base+id, map[string]any{"name": nil}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Patch(t, base+id, map[string]any{"base_url": nil}).Expect(http.StatusUnprocessableEntity)

	if s := w.Owner.Put(t, base+id+"/sharing", map[string]any{"shared": true}).Expect(http.StatusOK).Object(); s["personal"] != false {
		t.Fatalf("sharing %v", s)
	}
	w.Owner.Get(t, base+id+"/tool-policies").Expect(http.StatusOK)

	w.Owner.Delete(t, base+id).Expect(http.StatusOK, http.StatusNoContent)
	w.Owner.Get(t, base+id).Expect(http.StatusNotFound)
}

func TestOpenAPIConnectionValidationAndScope(t *testing.T) {
	w := h.NewWorkspace(t)
	base := w.Path("/openapi-connections/")
	w.Owner.Post(t, base, map[string]any{"base_url": "https://pets.invalid"}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Post(t, base, map[string]any{"name": "x"}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, base+missing).Expect(http.StatusNotFound)
	w.Owner.Post(t, base, map[string]any{"name": "x", "base_url": "https://pets.invalid/v1", "spec_content": petstore()}).
		Expect(http.StatusBadRequest).Match(h.Problem(http.StatusBadRequest, "bad_request", "Could not resolve host 'pets.invalid'"))

	id := str(t, w.Owner.Post(t, base, map[string]any{
		"name": "Scoped", "base_url": publicBase, "spec_content": petstore(),
	}).Expect(http.StatusCreated).Object(), "id")
	w.Outsider.Get(t, w.OutsiderPath("/openapi-connections/"+id)).Expect(http.StatusNotFound)
}

func TestLinkedAuthConfigCannotBeDeleted(t *testing.T) {
	w := h.NewWorkspace(t)
	auth := str(t, w.Owner.Post(t, w.Path("/mcp-auth-configs/"), map[string]any{
		"name": "Pets token", "auth_type": "bearer", "credentials": map[string]any{"token": "pet-token"},
	}).Expect(http.StatusCreated).Object(), "id")
	conn := str(t, w.Owner.Post(t, w.Path("/openapi-connections/"), map[string]any{
		"name": "Pets", "base_url": publicBase, "spec_content": petstore(), "auth_config_id": auth,
	}).Expect(http.StatusCreated).Object(), "id")

	refused := w.Owner.Delete(t, w.Path("/mcp-auth-configs/"+auth)).Expect(http.StatusConflict).Object()
	if d, _ := refused["detail"].(string); !strings.HasPrefix(d, "Cannot delete auth config "+auth+": linked to connections") {
		t.Fatalf("409 detail %v", refused["detail"])
	}

	w.Owner.Delete(t, w.Path("/openapi-connections/"+conn)).Expect(http.StatusOK, http.StatusNoContent)
	w.Owner.Delete(t, w.Path("/mcp-auth-configs/"+auth)).Expect(http.StatusNoContent)
}
