//go:build suite

package connections

import (
	"encoding/json"
	"net/http"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

// callTool is one tools/call: its text and whether it is a refusal.
func callTool(t *testing.T, c *h.Client, path, name string, args map[string]any) (string, bool) {
	t.Helper()
	res := obj(t, rpc(t, c, path, 7, "tools/call", map[string]any{"name": name, "arguments": args}).Expect(http.StatusOK).Object(), "result")
	content, ok := res["content"].([]any)
	if !ok || len(content) == 0 {
		t.Fatalf("%s: %v", name, res)
	}
	text, _ := content[0].(map[string]any)["text"].(string)
	isError, _ := res["isError"].(bool)
	return text, isError
}

func TestPlatformToolsOverMCP(t *testing.T) {
	w := h.NewWorkspace(t)
	key := w.APIKey(t)
	pinned := "/mcp/w/" + w.Slug

	text, failed := callTool(t, key, pinned, "projects_create", map[string]any{"name": "Platform tools"})
	var project struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if failed || json.Unmarshal([]byte(text), &project) != nil || project.Name != "Platform tools" {
		t.Fatalf("projects_create: %s", text)
	}
	if text, failed = callTool(t, key, "/mcp", "projects_get", map[string]any{"workspace": w.Slug, "project_id": project.ID}); failed || !strings.Contains(text, project.ID) {
		t.Fatalf("projects_get over the spanning mount: %s", text)
	}
	if text, failed = callTool(t, key, pinned, "projects_get", map[string]any{"project_id": missing}); !failed || text != "Project not found" {
		t.Fatalf("projects_get missing: %s", text)
	}
	if text, failed = callTool(t, key, pinned, "policies_list", map[string]any{}); failed || !strings.HasPrefix(text, "[") {
		t.Fatalf("policies_list: %s", text)
	}
	if text, failed = callTool(t, key, pinned, "network_get_topology", map[string]any{}); failed || !strings.Contains(text, `"nodes"`) {
		t.Fatalf("network_get_topology: %s", text)
	}
	if text, failed = callTool(t, key, pinned, "workspace_files_list", map[string]any{}); failed || !strings.HasPrefix(text, "[") {
		t.Fatalf("workspace_files_list: %s", text)
	}

	if text, failed = callTool(t, w.Member, pinned, "policies_list", map[string]any{}); !failed || text != "Only a workspace admin may perform this action" {
		t.Fatalf("member policies_list: %s", text)
	}
}
