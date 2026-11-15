//go:build suite

// Package connections pins the connections module's HTTP surface: MCP auth
// configs, MCP server instances, OpenAPI connections and the MCP endpoints
// (.omc/research/go-migration/dossiers/connections.md).
package connections

import (
	"net/http"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

const missing = "00000000-0000-4000-8000-000000000000"

// unresolvable never resolves (RFC 6761), so the endpoint check lets it
// through and verification fails without reaching any network.
const unresolvable = "https://mcp.invalid/mcp"

func str(t *testing.T, o map[string]any, key string) string {
	t.Helper()
	s, ok := o[key].(string)
	if !ok {
		t.Fatalf("%s = %#v, want a string", key, o[key])
	}
	return s
}

func obj(t *testing.T, o map[string]any, key string) map[string]any {
	t.Helper()
	m, ok := o[key].(map[string]any)
	if !ok {
		t.Fatalf("%s = %#v, want an object", key, o[key])
	}
	return m
}

func TestAuthConfigCRUDNeverShowsCredentials(t *testing.T) {
	w := h.NewWorkspace(t)
	base := w.Path("/mcp-auth-configs/")

	created := w.Owner.Post(t, base, map[string]any{
		"name": "Search key", "auth_type": "api_key",
		"config":      map[string]any{"header_name": "X-Api-Key"},
		"credentials": map[string]any{"header_value": "s3cret-value"},
	}).Expect(http.StatusCreated).Match(map[string]any{
		"id": h.AnyUUID, "name": "Search key", "description": nil, "auth_type": "api_key",
		"config": map[string]any{"header_name": "X-Api-Key"}, "created_at": h.AnyTimestamp, "updated_at": h.AnyTimestamp,
	}).Object()
	id := str(t, created, "id")

	w.Owner.Post(t, base, map[string]any{
		"name": "Token", "auth_type": "bearer", "credentials": map[string]any{"token": "t0ken"},
	}).Expect(http.StatusCreated)

	list := w.Owner.Get(t, base).Expect(http.StatusOK)
	if got := string(list.Body); strings.Contains(got, "s3cret-value") || strings.Contains(got, "t0ken") {
		t.Fatalf("a credential is in the list: %s", got)
	}
	if n := len(list.Array()); n != 2 {
		t.Fatalf("list has %d configs, want 2", n)
	}

	w.Owner.Put(t, base+id, map[string]any{"name": "Renamed", "credentials": map[string]any{"header_value": "rotated"}}).
		Expect(http.StatusOK).Match(map[string]any{
		"id": id, "name": "Renamed", "description": nil, "auth_type": "api_key",
		"config": map[string]any{"header_name": "X-Api-Key"}, "created_at": h.AnyTimestamp, "updated_at": h.AnyTimestamp,
	})

	w.Owner.Delete(t, base+id).Expect(http.StatusNoContent)
	w.Owner.Get(t, base+id).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "not_found", "MCP auth config not found"))
}

func TestAuthConfigRefusals(t *testing.T) {
	w := h.NewWorkspace(t)
	base := w.Path("/mcp-auth-configs/")
	w.Owner.Post(t, base, map[string]any{"name": "x", "auth_type": "basic"}).Expect(http.StatusBadRequest).
		Match(h.Problem(http.StatusBadRequest, "bad_request", "Invalid auth_type 'basic'. Must be one of {'api_key', 'bearer', 'oauth2'}"))
	w.Owner.Post(t, base, map[string]any{"name": "x", "auth_type": "bearer", "credentials": map[string]any{}}).
		Expect(http.StatusBadRequest)
	w.Owner.Post(t, base, map[string]any{"auth_type": "bearer"}).Expect(http.StatusUnprocessableEntity)
	w.Owner.Delete(t, base+missing).Expect(http.StatusNotFound)
	w.Owner.Get(t, base+"not-a-uuid").Expect(http.StatusUnprocessableEntity)
}

func TestAuthConfigsAreAdminOnly(t *testing.T) {
	w := h.NewWorkspace(t)
	w.Member.Get(t, w.Path("/mcp-auth-configs/")).Expect(http.StatusForbidden)
	w.Member.Post(t, w.Path("/mcp-auth-configs/"), map[string]any{
		"name": "t", "auth_type": "bearer", "credentials": map[string]any{"token": "x"},
	}).Expect(http.StatusForbidden)
	w.Anonymous.Get(t, w.Path("/mcp-auth-configs/")).Expect(http.StatusUnauthorized)
}
