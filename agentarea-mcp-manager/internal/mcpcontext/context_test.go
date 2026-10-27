package mcpcontext

import (
	"strings"
	"testing"

	"github.com/agentarea/mcp-manager/internal/models"
)

func instance(spec map[string]any) *models.MCPServerInstance {
	return &models.MCPServerInstance{InstanceID: "c92f0870-465a-4c70-8c11-b33d08fd8c54", JSONSpec: spec}
}

func TestOptedInInstanceGetsItsDerivedKey(t *testing.T) {
	env, err := NewIssuer([]byte("gateway-secret-of-at-least-32-bytes!!")).Environment(instance(map[string]any{"context": map[string]any{"enabled": true}}))
	if err != nil {
		t.Fatalf("Environment: %v", err)
	}
	// The same value agentarea_mcp.tool_context.derived_context_key returns for these inputs.
	const want = "4896aeffbc037762218722536c6b3909507c657b401b1dfd840e39b056c940f8"
	if got := env[KeyEnv]; got != want {
		t.Fatalf("key = %q, want %q", got, want)
	}
}

func TestKeyDependsOnSecretAndInstance(t *testing.T) {
	a := Key([]byte("secret-a"), "instance-1")
	if a == Key([]byte("secret-b"), "instance-1") || a == Key([]byte("secret-a"), "instance-2") {
		t.Fatal("key must change with the secret and the instance")
	}
	if a != Key([]byte("secret-a"), "instance-1") {
		t.Fatal("key must be deterministic")
	}
}

func TestInstanceWithoutTheFlagGetsNothing(t *testing.T) {
	env, err := NewIssuer([]byte("s")).Environment(instance(map[string]any{"storage": map[string]any{"enabled": true}}))
	if err != nil || env != nil {
		t.Fatalf("got %v, %v; want nothing", env, err)
	}
}

func TestMalformedFlagIsRefused(t *testing.T) {
	for _, value := range []any{true, map[string]any{"enabled": false}, map[string]any{"enabled": true, "x": 1}} {
		if _, err := NewIssuer([]byte("s")).Environment(instance(map[string]any{"context": value})); err == nil {
			t.Fatalf("%v was accepted", value)
		}
	}
}

func TestOptedInInstanceWithoutASecretFailsLoudly(t *testing.T) {
	_, err := (*Issuer)(nil).Environment(instance(map[string]any{"context": map[string]any{"enabled": true}}))
	if err == nil || !strings.Contains(err.Error(), "caller context") {
		t.Fatalf("err = %v", err)
	}
}
