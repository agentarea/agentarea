package mcpstorage

import (
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/models"
)

func TestEnabledAcceptsOnlyTheExactOptIn(t *testing.T) {
	cases := []struct {
		name    string
		spec    map[string]any
		want    bool
		wantErr bool
	}{
		{"absent", map[string]any{"type": "docker"}, false, false},
		{"null", map[string]any{"storage": nil}, false, false},
		{"opted in", map[string]any{"storage": map[string]any{"enabled": true}}, true, false},
		{"disabled", map[string]any{"storage": map[string]any{"enabled": false}}, false, true},
		{"extra key", map[string]any{"storage": map[string]any{"enabled": true, "quota": 1.0}}, false, true},
		{"empty", map[string]any{"storage": map[string]any{}}, false, true},
		{"string", map[string]any{"storage": "s3"}, false, true},
		{"truthy number", map[string]any{"storage": map[string]any{"enabled": 1.0}}, false, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := Enabled(tc.spec)
			if (err != nil) != tc.wantErr || got != tc.want {
				t.Fatalf("Enabled() = %v, %v; want %v, error=%v", got, err, tc.want, tc.wantErr)
			}
		})
	}
}

func TestIssuerHandsAnOptedInInstanceAURLAndAScopedToken(t *testing.T) {
	issuer := NewIssuer(testSecret, "http://mcp-manager:80")
	env, err := issuer.Environment(&models.MCPServerInstance{
		InstanceID: "inst-1", WorkspaceID: "ws-1",
		JSONSpec: map[string]any{"storage": map[string]any{"enabled": true}},
	})
	if err != nil {
		t.Fatalf("Environment() error = %v", err)
	}
	if len(env) != 2 || env["MCP_MANAGER_URL"] != "http://mcp-manager:80" {
		t.Fatalf("Environment() = %v", env)
	}
	if err := activationauth.Verify(env["MCP_STORAGE_TOKEN"], testSecret, activationauth.ScopeStorage, identity("ws-1", "inst-1"), activationauth.BodySHA256(nil), time.Now().Add(TokenTTL-time.Minute)); err != nil {
		t.Fatalf("token does not grant its instance: %v", err)
	}
}

func TestIssuerGivesNothingToAnInstanceThatDoesNotOptIn(t *testing.T) {
	env, err := NewIssuer(testSecret, "").Environment(&models.MCPServerInstance{InstanceID: "inst-1", WorkspaceID: "ws-1", JSONSpec: map[string]any{}})
	if err != nil || env != nil {
		t.Fatalf("Environment() = %v, %v; want nothing", env, err)
	}
}

func TestIssuerRefusesAnOptedInInstanceWithoutAManagerURL(t *testing.T) {
	_, err := NewIssuer(testSecret, "").Environment(&models.MCPServerInstance{
		InstanceID: "inst-1", WorkspaceID: "ws-1",
		JSONSpec: map[string]any{"storage": map[string]any{"enabled": true}},
	})
	if err == nil || !strings.Contains(err.Error(), "MCP_MANAGER_URL") {
		t.Fatalf("Environment() error = %v", err)
	}
}

func TestParseManagerURL(t *testing.T) {
	if got, err := ParseManagerURL("http://mcp-manager:80/"); err != nil || got != "http://mcp-manager:80" {
		t.Fatalf("ParseManagerURL() = %q, %v", got, err)
	}
	if got, err := ParseManagerURL(""); err != nil || got != "" {
		t.Fatalf("ParseManagerURL(empty) = %q, %v", got, err)
	}
	for _, raw := range []string{"mcp-manager:80", "/relative", "http://user:pw@host", "http://host?x=1"} { // pragma: allowlist secret
		if _, err := ParseManagerURL(raw); err == nil {
			t.Fatalf("ParseManagerURL(%q) accepted it", raw)
		}
	}
}
