package contract

import (
	"encoding/json"
	"slices"
	"testing"
)

func TestRoutesInventory(t *testing.T) {
	r, err := LoadRoutes()
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Routes) != 356 {
		t.Fatalf("routes: %d, want 356", len(r.Routes))
	}
	kinds := map[string]int{}
	inOpenAPI := 0
	for _, x := range r.Routes {
		kinds[x.Streaming]++
		if x.InOpenAPI {
			inOpenAPI++
		}
	}
	want := map[string]int{StreamingNone: 342, StreamingMounted: 8, StreamingSSE: 3, StreamingBody: 2, StreamingWS: 1}
	for k, n := range want {
		if kinds[k] != n {
			t.Errorf("streaming %s: %d, want %d", k, kinds[k], n)
		}
	}
	if len(kinds) != len(want) {
		t.Errorf("streaming kinds %v", kinds)
	}
	if inOpenAPI != 343 {
		t.Errorf("in OpenAPI: %d, want 343", inOpenAPI)
	}
}

func TestRoutesTheProxyMustCarry(t *testing.T) {
	r, err := LoadRoutes()
	if err != nil {
		t.Fatal(err)
	}
	have := map[string]Route{}
	for _, x := range r.Routes {
		key := x.Pattern()
		if x.Host != nil {
			key = *x.Host + " " + key
		}
		have[key] = x
	}
	for _, p := range []string{
		"WS /v1/runner/connect",
		"* /mcp", "* /mcp/w", "* /mcp/clients", "* /client-mcp", "* /static",
		"GET /v1/mcp/{instance_id}/mcp", "POST /v1/mcp/{instance_id}/mcp", "DELETE /v1/mcp/{instance_id}/mcp",
		"GET /v1/workspaces/{workspace}/agents/{agent_id}/tasks/{task_id}/events/stream",
		"POST /v1/workspaces/{workspace}/agents/{agent_id}/tasks/",
		"GET /v1/workspaces/{workspace}/streams/events/live",
		"GET /v1/workspaces/{workspace}/files/download/{file_path...}",
		"GET /oauth2/{path...}", "POST /webhooks/{webhook_id}", "GET /.well-known/jwks.json",
		"{agent_id:uuid}.a2a.localhost POST /", "{agent_id:uuid}.a2a.localhost GET /.well-known/agent-card.json",
		"GET /health",
	} {
		if _, ok := have[p]; !ok {
			t.Errorf("contract lacks %s", p)
		}
	}
}

func TestPatternRewritesPathConverters(t *testing.T) {
	r := Route{Method: "GET", Path: "/v1/workspaces/{workspace}/files/download/{file_path:path}"}
	if got := r.Pattern(); got != "GET /v1/workspaces/{workspace}/files/download/{file_path...}" {
		t.Fatal(got)
	}
}

func TestMCPTools(t *testing.T) {
	m, err := LoadMCPTools()
	if err != nil {
		t.Fatal(err)
	}
	spanning, pinned := m.PlatformSpanning, m.PlatformPinned
	if spanning.Mount != "/mcp" || len(spanning.Tools) != 138 {
		t.Fatalf("spanning: %s %d tools", spanning.Mount, len(spanning.Tools))
	}
	if pinned.Mount != "/mcp/w/{workspace}" || len(pinned.Tools) != 135 {
		t.Fatalf("pinned: %s %d tools", pinned.Mount, len(pinned.Tools))
	}
	if len(m.ClientMCP.Tools) != 0 || len(m.ConnectionMCP.Tools) != 0 {
		t.Fatal("dynamic servers carry no tools")
	}
	pinnedNames := map[string]bool{}
	for _, tool := range pinned.Tools {
		pinnedNames[tool.Name] = true
	}
	toolsets := map[string]bool{}
	seen := map[string]bool{}
	var onlySpanning []string
	for _, tool := range spanning.Tools {
		if seen[tool.Name] {
			t.Errorf("tool %s listed twice", tool.Name)
		}
		seen[tool.Name] = true
		toolsets[tool.Toolset] = true
		if !pinnedNames[tool.Name] {
			onlySpanning = append(onlySpanning, tool.Name)
		}
		var schema struct {
			Required []string `json:"required"`
		}
		if err := json.Unmarshal(tool.InputSchema, &schema); err != nil {
			t.Fatalf("%s: %v", tool.Name, err)
		}
		needsWorkspace := tool.Name != "workspaces_create" && tool.Name != "workspaces_list"
		if slices.Contains(schema.Required, "workspace") != needsWorkspace {
			t.Errorf("%s: required workspace argument is %v", tool.Name, !needsWorkspace)
		}
	}
	slices.Sort(onlySpanning)
	if !slices.Equal(onlySpanning, []string{"workspaces_create", "workspaces_list", "workspaces_update"}) {
		t.Errorf("tools only on /mcp: %v", onlySpanning)
	}
	if len(toolsets) != 24 || !toolsets["workspaces"] {
		t.Errorf("toolsets: %d, want 24 incl. workspaces", len(toolsets))
	}
}
