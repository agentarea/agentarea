package providers

import (
	"reflect"
	"testing"
)

type recordingSecretResolver struct {
	instanceValues map[string]string
	omit           map[string]bool
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
	_, err := resolveInstanceSpecSecrets(resolver, "instance-1", map[string]any{
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

	resolved, err := resolveInstanceSpecSecrets(resolver, "instance-1", source)
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
	_, err := resolveInstanceSpecSecrets(nil, "instance-1", map[string]any{
		"env_vars": []any{"NAMED"},
	})
	if err == nil {
		t.Fatal("expected missing resolver to fail closed")
	}
}

func TestResolveInstanceSpecSecretsAllowsPlainEnvironmentWithoutResolver(t *testing.T) {
	resolved, err := resolveInstanceSpecSecrets(nil, "instance-1", map[string]any{
		"environment": map[string]string{"PLAIN": "value"},
	})
	if err != nil {
		t.Fatalf("resolve plain environment: %v", err)
	}
	if got := resolved["environment"].(map[string]any)["PLAIN"]; got != "value" {
		t.Fatalf("PLAIN = %#v, want value", got)
	}
}
