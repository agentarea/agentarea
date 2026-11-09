package providers

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"reflect"
	"testing"

	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/secrets"
)

type workspaceSecretKey struct{ workspace, name string }

type recordingSecretResolver struct {
	instanceValues  map[string]string
	omit            map[string]bool
	workspaceValues map[workspaceSecretKey]string
	askedWorkspaces []string
}

func (r *recordingSecretResolver) ResolveWorkspaceSecret(_ context.Context, workspaceID, secretName string) (string, error) {
	r.askedWorkspaces = append(r.askedWorkspaces, workspaceID)
	value, ok := r.workspaceValues[workspaceSecretKey{workspaceID, secretName}]
	if !ok {
		return "", errors.New("secret not found")
	}
	return value, nil
}

func resolveSpec(resolver *recordingSecretResolver, workspaceID string, source map[string]any) (map[string]any, error) {
	instance := &models.MCPServerInstance{InstanceID: "instance-1", WorkspaceID: workspaceID, JSONSpec: source}
	var secretResolver secrets.SecretResolver
	if resolver != nil {
		secretResolver = resolver
	}
	return resolveInstanceSpecSecrets(context.Background(), secretResolver, slog.New(slog.NewTextHandler(io.Discard, nil)), instance)
}

func (r *recordingSecretResolver) ResolveInstanceEnvVars(_ string, names []string) (map[string]string, error) {
	resolved := make(map[string]string, len(names))
	for _, name := range names {
		if r.omit[name] {
			continue
		}
		resolved[name] = r.instanceValues[name]
	}
	return resolved, nil
}

func TestResolveInstanceSpecSecretsRejectsOmittedRequestedSecret(t *testing.T) {
	resolver := &recordingSecretResolver{omit: map[string]bool{"MISSING": true}}
	_, err := resolveSpec(resolver, "ws-1", map[string]any{
		"env_vars": []any{"MISSING"},
	})
	if err == nil {
		t.Fatal("expected omitted requested secret to fail closed")
	}
}

func (r *recordingSecretResolver) Close() error { return nil }

func TestResolveInstanceSpecSecretsMergesNamedSecretsIntoEnvironment(t *testing.T) {
	source := map[string]any{
		"environment": map[string]any{"PLAIN": "value"},
		"env_vars":    []any{"NAMED"},
	}
	resolver := &recordingSecretResolver{instanceValues: map[string]string{"NAMED": "named-secret"}}

	resolved, err := resolveSpec(resolver, "ws-1", source)
	if err != nil {
		t.Fatalf("resolve secrets: %v", err)
	}

	want := map[string]any{
		"PLAIN": "value",
		"NAMED": "named-secret",
	}
	if got := resolved["environment"]; !reflect.DeepEqual(got, want) {
		t.Fatalf("environment = %#v, want %#v", got, want)
	}
	if _, mutated := source["environment"].(map[string]any)["NAMED"]; mutated {
		t.Fatal("source mutated: NAMED leaked into the caller's spec")
	}
}

func TestResolveInstanceSpecSecretsRequiresResolverForNamedSecrets(t *testing.T) {
	_, err := resolveSpec(nil, "ws-1", map[string]any{
		"env_vars": []any{"NAMED"},
	})
	if err == nil {
		t.Fatal("expected missing resolver to fail closed")
	}
}

func TestResolveInstanceSpecSecretsAllowsPlainEnvironmentWithoutResolver(t *testing.T) {
	resolved, err := resolveSpec(nil, "ws-1", map[string]any{
		"environment": map[string]string{"PLAIN": "value"},
	})
	if err != nil {
		t.Fatalf("resolve plain environment: %v", err)
	}
	if got := resolved["environment"].(map[string]any)["PLAIN"]; got != "value" {
		t.Fatalf("PLAIN = %#v, want value", got)
	}
}

func TestResolveInstanceSpecSecretsResolvesAReferenceInTheInstanceWorkspace(t *testing.T) {
	resolver := &recordingSecretResolver{
		instanceValues: map[string]string{"COPIED": "copied-value"},
		workspaceValues: map[workspaceSecretKey]string{
			{"ws-1", "openai-key"}:     "own-value",
			{"ws-other", "openai-key"}: "other-value",
		},
	}
	resolved, err := resolveSpec(resolver, "ws-1", map[string]any{
		"environment": map[string]any{"API_KEY": map[string]any{"secret_name": "openai-key"}, "PLAIN": "x"},
		"env_vars":    []any{"COPIED"},
	})
	if err != nil {
		t.Fatalf("resolve secrets: %v", err)
	}
	want := map[string]any{"API_KEY": "own-value", "PLAIN": "x", "COPIED": "copied-value"}
	if got := resolved["environment"]; !reflect.DeepEqual(got, want) {
		t.Fatalf("environment = %#v, want %#v", got, want)
	}
	if !reflect.DeepEqual(resolver.askedWorkspaces, []string{"ws-1"}) {
		t.Fatalf("resolver asked workspaces %v, want only the instance's ws-1", resolver.askedWorkspaces)
	}
}

func TestResolveInstanceSpecSecretsFailsOnAMissingReferencedSecret(t *testing.T) {
	resolver := &recordingSecretResolver{workspaceValues: map[workspaceSecretKey]string{{"ws-other", "openai-key"}: "other-value"}}
	resolved, err := resolveSpec(resolver, "ws-1", map[string]any{
		"environment": map[string]any{"API_KEY": map[string]any{"secret_name": "openai-key"}, "PLAIN": "x"},
	})
	if err == nil || resolved != nil {
		t.Fatalf("resolveInstanceSpecSecrets() = %#v, %v; want no spec and an error", resolved, err)
	}
}

func TestBuildBackendInstanceSpecResolvesAReferencedSecret(t *testing.T) {
	resolver := &recordingSecretResolver{workspaceValues: map[workspaceSecretKey]string{{"ws-1", "gh-token"}: "token-value"}}
	spec, err := BuildBackendInstanceSpec(context.Background(), &models.MCPServerInstance{
		InstanceID:  "instance-1",
		WorkspaceID: "ws-1",
		JSONSpec: map[string]any{
			"type":        "command",
			"command":     "npx",
			"environment": map[string]any{"GITHUB_TOKEN": map[string]any{"secret_name": "gh-token"}},
		},
	}, resolver, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatalf("BuildBackendInstanceSpec() error = %v", err)
	}
	if spec.Environment["GITHUB_TOKEN"] != "token-value" {
		t.Fatalf("GITHUB_TOKEN = %q, want the referenced secret", spec.Environment["GITHUB_TOKEN"])
	}
}
