//go:build suite

package agents

import (
	"net/http"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

func a2aAgent(t *testing.T, w *h.Workspace) string {
	t.Helper()
	return create(t, w.Owner, w, map[string]any{"name": "Helper", "tools": []any{}, "planning": true})["id"].(string)
}

func a2aRPC(t *testing.T, c *h.Client, id, version string, body any) *h.Response {
	t.Helper()
	header := http.Header{}
	if version != "" {
		header.Set("A2A-Version", version)
	}
	return c.Do(t, h.Request{Method: http.MethodPost, Path: "/v1/agents/" + id + "/a2a/rpc", Body: body, Header: header})
}

func TestA2ADiscoveryIsAnonymous(t *testing.T) {
	w := h.NewWorkspace(t)
	id := a2aAgent(t, w)
	card := w.Anonymous.Get(t, "/v1/agents/"+id+"/.well-known/agent-card.json").Expect(http.StatusOK).Object()
	if card["name"] != "Helper" || card["description"] != "AI agent Helper" || card["version"] != "1.0.0" {
		t.Fatalf("card %v", card)
	}
	if len(card["skills"].([]any)) != 1 {
		t.Fatalf("public card skills %v", card["skills"])
	}
	info := w.Anonymous.Get(t, "/v1/agents/"+id+"/.well-known/a2a-info.json").Expect(http.StatusOK).Object()
	if info["protocol"] != "A2A" || info["agent"].(map[string]any)["status"] != "active" {
		t.Fatalf("info %v", info)
	}
	w.Anonymous.Get(t, "/v1/agents/"+id+"/.well-known/").Expect(http.StatusOK)
	w.Anonymous.Get(t, "/v1/agents/00000000-0000-4000-8000-000000000000/.well-known/agent-card.json").
		Expect(http.StatusNotFound).Match(h.Problem(http.StatusNotFound, "http_error", "Agent 00000000-0000-4000-8000-000000000000 not found"))
	w.Anonymous.Get(t, "/v1/agents/nope/.well-known/agent-card.json").Expect(http.StatusUnprocessableEntity)
}

func TestA2ARPCAuthorizesAgainstTheAgentsWorkspace(t *testing.T) {
	w := h.NewWorkspace(t)
	id := a2aAgent(t, w)
	body := map[string]any{"jsonrpc": "2.0", "id": 1, "method": "GetExtendedAgentCard"}
	resp := a2aRPC(t, w.Anonymous, id, "1.0", body).Expect(http.StatusUnauthorized)
	if resp.Header.Get("WWW-Authenticate") != "Bearer" {
		t.Fatalf("challenge %q", resp.Header.Get("WWW-Authenticate"))
	}
	resp.Match(h.Problem(http.StatusUnauthorized, "http_error", "Authentication required"))
	a2aRPC(t, w.Outsider, id, "1.0", body).Expect(http.StatusForbidden).
		Match(h.Problem(http.StatusForbidden, "http_error", "Insufficient permissions. Required: agent:read"))
	a2aRPC(t, w.Owner, "nope", "1.0", body).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Agent not found"))
	w.Anonymous.Get(t, "/v1/agents/"+id+"/a2a/well-known").Expect(http.StatusUnauthorized)
	w.Member.Get(t, "/v1/agents/"+id+"/a2a/well-known").Expect(http.StatusOK)
}

func TestA2AGetExtendedAgentCard(t *testing.T) {
	w := h.NewWorkspace(t)
	id := a2aAgent(t, w)
	got := a2aRPC(t, w.Owner, id, "1.0", map[string]any{"jsonrpc": "2.0", "id": "r1", "method": "GetExtendedAgentCard"}).
		Expect(http.StatusOK).Object()
	if got["id"] != "r1" || got["jsonrpc"] != "2.0" {
		t.Fatalf("envelope %v", got)
	}
	skills := got["result"].(map[string]any)["skills"].([]any)
	if len(skills) != 2 || skills[1].(map[string]any)["id"] != "task-planning" {
		t.Fatalf("extended skills %v", skills)
	}
	a2aRPC(t, w.Owner, id, "", map[string]any{"jsonrpc": "2.0", "id": 2, "method": "GetExtendedAgentCard"}).
		Expect(http.StatusOK).Match(map[string]any{"id": 2.0, "jsonrpc": "2.0", "error": map[string]any{
		"code": -32009.0, "message": "A2A version '0.3' is not supported by this handler. Expected version '1.0'.",
		"data": []any{map[string]any{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "VERSION_NOT_SUPPORTED", "domain": "a2a-protocol.org", "metadata": map[string]any{}}},
	}})
	a2aRPC(t, w.Owner, id, "1.0", map[string]any{"jsonrpc": "2.0", "id": 3, "method": "Nope"}).
		Expect(http.StatusOK).Match(map[string]any{"id": 3.0, "jsonrpc": "2.0", "error": map[string]any{"code": -32601.0, "message": "Method not found"}})
	a2aRPC(t, w.Owner, id, "1.0", []any{}).
		Expect(http.StatusOK).Match(map[string]any{"id": nil, "jsonrpc": "2.0", "error": map[string]any{
		"code": -32600.0, "message": "Invalid Request", "data": "[] value is not accepted"}})
}

func TestA2AReadAgentCardRefusesAnUnreachableAddress(t *testing.T) {
	w := h.NewWorkspace(t)
	resp := w.Member.Post(t, w.Path("/a2a/agent-cards"), map[string]any{"url": "http://127.0.0.1:9/.well-known/agent-card.json"}).
		Expect(http.StatusBadRequest).Object()
	if detail, _ := resp["detail"].(string); len(detail) < 30 || detail[:30] != "No agent card at http://127.0." {
		t.Fatalf("detail %v", resp["detail"])
	}
	w.Member.Post(t, w.Path("/a2a/agent-cards"), map[string]any{}).Expect(http.StatusUnprocessableEntity)
}
