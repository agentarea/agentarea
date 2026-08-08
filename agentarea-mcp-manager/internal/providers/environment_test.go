package providers

import (
	"reflect"
	"testing"
)

type recordingSecretResolver struct {
	instanceValues map[string]string
	omit           map[string]bool
}

func (r *recordingSecretResolver) ResolveSecrets(_ string, values map[string]string) (map[string]string, error) {
	resolved := make(map[string]string, len(values))
	for key, value := range values {
		if value == "secret_ref:" {
			resolved[key] = "resolved-reference"
		} else {
			resolved[key] = value
		}
	}
	return resolved, nil
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

func TestResolveInstanceSpecSecretsResolvesBothSecretForms(t *testing.T) {
	source := map[string]any{
		"environment": map[string]any{
			"PLAIN": "value",
			"REF":   "secret_ref:",
		},
		"env_vars": []any{"NAMED"},
	}
	resolver := &recordingSecretResolver{instanceValues: map[string]string{"NAMED": "named-secret"}}

	resolved, err := resolveInstanceSpecSecrets(resolver, "instance-1", source)
	if err != nil {
		t.Fatalf("resolve secrets: %v", err)
	}

	want := map[string]any{
		"PLAIN": "value",
		"REF":   "resolved-reference",
		"NAMED": "named-secret",
	}
	if got := resolved["environment"]; !reflect.DeepEqual(got, want) {
		t.Fatalf("environment = %#v, want %#v", got, want)
	}
	if got := source["environment"].(map[string]any)["REF"]; got != "secret_ref:" {
		t.Fatalf("source mutated: REF = %#v", got)
	}
}

func TestResolveInstanceSpecSecretsRequiresResolverForEmptyReference(t *testing.T) {
	_, err := resolveInstanceSpecSecrets(nil, "instance-1", map[string]any{
		"environment": map[string]any{"REF": "secret_ref:"},
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
