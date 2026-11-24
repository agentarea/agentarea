//go:build suite

package connections

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

const suitePaidItem = "5e1f0000-0000-4000-8000-000000000113"

func TestSpecCRUDBySlugAndID(t *testing.T) {
	w := h.NewWorkspace(t)
	base := w.Path("/mcp-servers/")
	sp := w.Owner.Post(t, base, map[string]any{
		"name": "  Weather Spec ", "description": "forecasts", "docker_image_url": "ghcr.io/acme/weather:1",
		"tags": []any{"weather"}, "is_public": true, "cmd": []any{"serve", "--http"},
	}).Expect(http.StatusOK).Object()
	id := str(t, sp, "id")
	if sp["slug"] != "weather-spec" || sp["name"] != "Weather Spec" || sp["status"] != "draft" || sp["is_public"] != true ||
		sp["version"] != "1.0.0" || sp["registry_item_id"] != nil {
		t.Fatalf("create %v", sp)
	}

	w.Owner.Get(t, w.Path("/mcp-servers/weather-spec")).Expect(http.StatusOK).Object()
	w.Owner.Get(t, w.Path("/mcp-servers/no-such-slug")).Expect(http.StatusNotFound)

	patched := w.Owner.Patch(t, w.Path("/mcp-servers/"+id), map[string]any{"description": "rain", "remote_url": nil}).
		Expect(http.StatusOK).Object()
	if patched["description"] != "rain" || patched["name"] != "Weather Spec" || patched["cmd"] == nil {
		t.Fatalf("patch %v", patched)
	}
	w.Owner.Patch(t, w.Path("/mcp-servers/"+id), map[string]any{"name": nil}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Patch(t, w.Path("/mcp-servers/"+id), map[string]any{"bogus": 1}).Expect(http.StatusUnprocessableEntity)

	w.Owner.Post(t, w.Path("/mcp-servers/weather-spec/deploy"), nil).Expect(http.StatusOK).
		Match(map[string]any{"status": "success", "message": "MCP server Weather Spec deployed successfully"})
	if got := w.Owner.Get(t, w.Path("/mcp-servers/"+id)).Expect(http.StatusOK).Object(); got["status"] != "deployed" {
		t.Fatalf("after deploy %v", got)
	}

	w.Owner.Delete(t, w.Path("/mcp-servers/"+id)).Expect(http.StatusOK).Match(map[string]any{"status": "success"})
	w.Owner.Get(t, w.Path("/mcp-servers/"+id)).Expect(http.StatusNotFound)
}

func TestSpecListShowsOwnSpecsThenTheCatalog(t *testing.T) {
	w := h.NewWorkspace(t)
	id := str(t, w.Owner.Post(t, w.Path("/mcp-servers/"), map[string]any{"name": "Listed Spec", "description": "d"}).
		Expect(http.StatusOK).Object(), "id")

	page := w.Owner.Get(t, w.Path("/mcp-servers/?page_size=1")).Expect(http.StatusOK).Object()
	items := page["items"].([]any)
	if len(items) != 1 || items[0].(map[string]any)["id"] != id || page["has_next"] != true {
		t.Fatalf("first page %v", page)
	}
	byID := w.Owner.Get(t, w.Path("/mcp-servers/?ids="+id+"&ids="+suitePaidItem)).Expect(http.StatusOK).Object()
	if got := byID["items"].([]any); len(got) != 2 || fmt.Sprint(byID["page_size"]) != "2" {
		t.Fatalf("by ids %v", byID)
	}
	draft := w.Owner.Get(t, w.Path("/mcp-servers/?status=draft")).Expect(http.StatusOK).Object()
	for _, it := range draft["items"].([]any) {
		if it.(map[string]any)["status"] != "draft" {
			t.Fatalf("status filter let through %v", it)
		}
	}
	w.Owner.Get(t, w.Path("/mcp-servers/?ids=nope")).Expect(http.StatusUnprocessableEntity)
	w.Owner.Get(t, w.Path("/mcp-servers/"+suitePaidItem)).Expect(http.StatusOK)
}

func TestSpecRefusals(t *testing.T) {
	w := h.NewWorkspace(t)
	base := w.Path("/mcp-servers/")
	w.Owner.Post(t, base, map[string]any{"name": "Local", "description": "d", "remote_url": "http://169.254.169.254/mcp"}).
		Expect(http.StatusUnprocessableEntity, http.StatusBadRequest)
	w.Owner.Post(t, base, map[string]any{"name": "Ref", "description": "d",
		"json_spec": map[string]any{"type": "url", "endpoint_url": "https://example.com/mcp", "headers": map[string]any{"A": map[string]any{"secret_name": "x"}}}}).
		Expect(http.StatusUnprocessableEntity, http.StatusBadRequest)
	w.Owner.Post(t, base, map[string]any{"description": "d"}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Patch(t, w.Path("/mcp-servers/"+suitePaidItem), map[string]any{"name": "mine"}).Expect(http.StatusForbidden, http.StatusNotFound)
	w.Owner.Delete(t, w.Path("/mcp-servers/"+suitePaidItem)).Expect(http.StatusForbidden, http.StatusNotFound)

	id := str(t, w.Owner.Post(t, base, map[string]any{"name": "Owned", "description": "d"}).Expect(http.StatusOK).Object(), "id")
	w.Outsider.Get(t, w.OutsiderPath("/mcp-servers/"+id)).Expect(http.StatusForbidden, http.StatusNotFound)
}

func TestSpecToolsOverMCP(t *testing.T) {
	w := h.NewWorkspace(t)
	key := w.APIKey(t)
	pinned := "/mcp/w/" + w.Slug

	text, failed := callTool(t, key, pinned, "mcp_servers_create_spec", map[string]any{"name": "Tool Spec", "description": "d", "tags": []any{"t"}})
	var sp struct {
		ID     string `json:"id"`
		Status string `json:"status"`
	}
	if failed || json.Unmarshal([]byte(text), &sp) != nil || sp.ID == "" || sp.Status != "draft" {
		t.Fatalf("create_spec: %s", text)
	}
	if text, failed = callTool(t, key, pinned, "mcp_servers_update_spec", map[string]any{"spec_id": sp.ID, "status": "active"}); failed || !strings.Contains(text, `"status": "active"`) && !strings.Contains(text, `"status":"active"`) {
		t.Fatalf("update_spec: %s", text)
	}
	if text, failed = callTool(t, key, pinned, "mcp_servers_list_specs", map[string]any{"tag": "t"}); failed || !strings.Contains(text, sp.ID) {
		t.Fatalf("list_specs: %s", text)
	}
	if text, failed = callTool(t, key, pinned, "mcp_servers_get_spec", map[string]any{"spec_id": sp.ID}); failed || !strings.Contains(text, "Tool Spec") {
		t.Fatalf("get_spec: %s", text)
	}
	if text, failed = callTool(t, key, pinned, "mcp_servers_delete_spec", map[string]any{"spec_id": sp.ID}); failed || !strings.Contains(text, "true") {
		t.Fatalf("delete_spec: %s", text)
	}
	w.Owner.Get(t, w.Path("/mcp-servers/"+sp.ID)).Expect(http.StatusNotFound)
}
