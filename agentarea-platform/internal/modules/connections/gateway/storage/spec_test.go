package storage

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
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

func optedIn() map[string]any { return map[string]any{"storage": map[string]any{"enabled": true}} }

func TestIssuerHandsAnOptedInInstanceAURLAndAScopedToken(t *testing.T) {
	env, err := NewIssuer(testSecret(), "http://mcp-manager:80").Environment("inst-1", "ws-1", optedIn())
	if err != nil {
		t.Fatalf("Environment() error = %v", err)
	}
	if len(env) != 2 || env[EnvManagerURL] != "http://mcp-manager:80" {
		t.Fatalf("Environment() = %v", env)
	}
	if err := verifyToken(env[EnvStorageToken], testSecret(), "ws-1", "inst-1", time.Now().Add(TokenTTL-time.Minute)); err != nil {
		t.Fatalf("token does not grant its instance: %v", err)
	}
}

func TestIssuerGivesNothingToAnInstanceThatDoesNotOptIn(t *testing.T) {
	env, err := NewIssuer(testSecret(), "").Environment("inst-1", "ws-1", map[string]any{})
	if err != nil || env != nil {
		t.Fatalf("Environment() = %v, %v; want nothing", env, err)
	}
}

func TestIssuerRefusesAnOptedInInstanceWithoutAManagerURL(t *testing.T) {
	_, err := NewIssuer(testSecret(), "").Environment("inst-1", "ws-1", optedIn())
	if err == nil || !strings.Contains(err.Error(), "AGENTAREA_MCP_STORAGE_URL") {
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

func load(env map[string]string) (Config, error) {
	l := config.New(func(name string) (string, bool) { v, ok := env[name]; return v, ok })
	cfg := LoadConfig(l)
	return cfg, l.Err()
}

func TestLoadConfig(t *testing.T) {
	for value, want := range map[string]ConditionalWrites{"": NativeConditionalWrites, "native": NativeConditionalWrites, "emulated": EmulatedConditionalWrites} {
		cfg, err := load(map[string]string{"AGENTAREA_S3_CONDITIONAL_WRITES": value, "AGENTAREA_MCP_STORAGE_URL": "http://mcp:80/"})
		if err != nil || cfg.Writes != want || cfg.ManagerURL != "http://mcp:80" {
			t.Fatalf("%q: got %+v, %v; want %q", value, cfg, err, want)
		}
	}
	if _, err := load(map[string]string{"AGENTAREA_S3_CONDITIONAL_WRITES": "off"}); err == nil {
		t.Fatal("an unknown conditional-writes mode was accepted")
	}
	if _, err := load(map[string]string{"AGENTAREA_MCP_STORAGE_URL": "mcp:80"}); err == nil {
		t.Fatal("a relative manager URL was accepted")
	}
}

func TestStorageTokenGrantsOneInstanceOfOneWorkspace(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	now := time.Unix(1_700_000_000, 0)
	token, err := signToken(secret, "workspace-1", "instance-1", now, 30*24*time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if err := verifyToken(token, secret, "workspace-1", "instance-1", now.Add(29*24*time.Hour)); err != nil {
		t.Fatalf("verifyToken() error = %v", err)
	}
	for name, other := range map[string][2]string{
		"instance":  {"workspace-1", "instance-2"},
		"workspace": {"workspace-2", "instance-1"},
	} {
		if err := verifyToken(token, secret, other[0], other[1], now); !errors.Is(err, errClaimsMismatch) {
			t.Fatalf("%s: verifyToken() error = %v, want errClaimsMismatch", name, err)
		}
	}
	if err := verifyToken(token, secret, "workspace-1", "instance-1", now.Add(30*24*time.Hour)); err == nil {
		t.Fatal("expired token was accepted")
	}
	for _, incomplete := range [][2]string{{"workspace-1", ""}, {"", "instance-1"}} {
		if _, err := signToken(secret, incomplete[0], incomplete[1], now, time.Hour); err == nil {
			t.Fatalf("signToken() accepted identity %v", incomplete)
		}
	}
}

func TestTamperedTokenIsRejected(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	now := time.Unix(1_700_000_000, 0)
	token, err := signToken(secret, "workspace-1", "instance-1", now, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	payload, signature, _ := strings.Cut(token, ".")
	for _, bad := range []string{payload + "x." + signature, payload + "." + signature + "x", payload, ""} {
		if err := verifyToken(bad, secret, "workspace-1", "instance-1", now); err == nil {
			t.Fatalf("tampered token %q was accepted", bad)
		}
	}
}

// A token mcp-manager minted for another scope (here the sandbox's files
// scope, task fields set) never opens storage.
func TestTaskScopedClaimsDoNotOpenStorage(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	now := time.Unix(1_700_000_000, 0)
	encoded := "eyJ2IjoyLCJzY29wZSI6ImZpbGVzIiwid29ya3NwYWNlX2lkIjoid29ya3NwYWNlLTEiLCJ0YXNrX2lkIjoidCIsImluc3RhbmNlX2lkIjoiaW5zdGFuY2UtMSIsImdlbmVyYXRpb24iOjAsImZlbmNpbmdfdG9rZW4iOjEsImJvZHlfc2hhMjU2IjoiIiwiZXhwaXJlc19hdCI6MTcwMDAwMzYwMCwibm9uY2UiOiIwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMCJ9"
	if err := verifyToken(encoded+"."+mac(encoded, secret), secret, "workspace-1", "instance-1", now); !errors.Is(err, errClaimsMismatch) {
		t.Fatalf("verifyToken() error = %v, want errClaimsMismatch", err)
	}
}
