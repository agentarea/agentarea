//go:build suite

package connections

import (
	"net/http"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func rpc(t *testing.T, c *h.Client, path string, id int, method string, params map[string]any) *h.Response {
	t.Helper()
	body := map[string]any{"jsonrpc": "2.0", "id": id, "method": method}
	if params != nil {
		body["params"] = params
	}
	return c.Do(t, h.Request{Method: http.MethodPost, Path: path, Body: body, Header: http.Header{
		"Accept": {"application/json, text/event-stream"},
	}})
}

func initialize() map[string]any {
	return map[string]any{
		"protocolVersion": "2025-06-18", "capabilities": map[string]any{},
		"clientInfo": map[string]any{"name": "suite", "version": "1"},
	}
}

func TestPlatformMCPInitializeAndListTools(t *testing.T) {
	w := h.NewWorkspace(t)
	key := w.APIKey(t)

	init := rpc(t, key, "/mcp", 1, "initialize", initialize()).Expect(http.StatusOK).Object()
	result := obj(t, init, "result")
	if result["protocolVersion"] == nil || obj(t, result, "serverInfo")["name"] == nil {
		t.Fatalf("initialize %v", init)
	}

	listed := rpc(t, key, "/mcp", 2, "tools/list", nil).Expect(http.StatusOK).Object()
	tools, ok := obj(t, listed, "result")["tools"].([]any)
	if !ok || len(tools) == 0 {
		t.Fatalf("tools/list %v", listed)
	}

	pinned := rpc(t, key, "/mcp/w/"+w.Slug, 3, "tools/list", nil).Expect(http.StatusOK).Object()
	if _, ok := obj(t, pinned, "result")["tools"].([]any); !ok {
		t.Fatalf("pinned tools/list %v", pinned)
	}
}

func TestPlatformMCPNeedsATokenBeyondTheHandshake(t *testing.T) {
	w := h.NewWorkspace(t)
	rpc(t, w.Anonymous, "/mcp", 1, "initialize", initialize()).Expect(http.StatusOK)

	resp := rpc(t, w.Anonymous, "/mcp", 2, "tools/list", nil).Expect(http.StatusUnauthorized)
	if resp.Header.Get("WWW-Authenticate") == "" {
		t.Fatal("401 without a WWW-Authenticate challenge")
	}
	if e := obj(t, resp.Object(), "error"); e["code"] == nil {
		t.Fatalf("401 body %s", resp.Body)
	}

	rpc(t, w.APIKey(t), "/mcp/w/"+w.OutsiderSlug, 3, "tools/list", nil).Expect(http.StatusForbidden)
}

func TestInstanceProxyUnknownInstanceIs404(t *testing.T) {
	w := h.NewWorkspace(t)
	rpc(t, w.Owner, "/v1/mcp/"+missing+"/mcp", 1, "initialize", initialize()).Expect(http.StatusNotFound, http.StatusForbidden)
	rpc(t, w.Anonymous, "/v1/mcp/"+missing+"/mcp", 1, "initialize", initialize()).Expect(http.StatusUnauthorized)
}
