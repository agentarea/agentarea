package secrets

import (
	"bytes"
	"context"
	"errors"
	"io"
	"log/slog"
	"reflect"
	"strings"
	"testing"
)

type workspaceSecret struct{ workspace, name string }

type workspaceSecretStub struct {
	values map[workspaceSecret]string
	err    error
	asked  []workspaceSecret
}

func (s *workspaceSecretStub) ResolveWorkspaceSecret(_ context.Context, workspaceID, secretName string) (string, error) {
	s.asked = append(s.asked, workspaceSecret{workspaceID, secretName})
	if s.err != nil {
		return "", s.err
	}
	value, ok := s.values[workspaceSecret{workspaceID, secretName}]
	if !ok {
		return "", errors.New("secret not found")
	}
	return value, nil
}

func discardLogger() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

func TestResolveValuesReadsReferenceFromTheInstanceWorkspace(t *testing.T) {
	stub := &workspaceSecretStub{values: map[workspaceSecret]string{
		{"ws-own", "openai-key"}:   "own-value",
		{"ws-other", "openai-key"}: "other-value",
	}}

	got, err := ResolveValues(context.Background(), stub, discardLogger(), "ws-own", "inst-1", map[string]any{
		"API_KEY": map[string]any{"secret_name": "openai-key"},
		"PLAIN":   "x",
	})
	if err != nil {
		t.Fatalf("ResolveValues() error = %v", err)
	}
	if want := map[string]string{"API_KEY": "own-value", "PLAIN": "x"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("ResolveValues() = %#v, want %#v", got, want)
	}
	if want := []workspaceSecret{{"ws-own", "openai-key"}}; !reflect.DeepEqual(stub.asked, want) {
		t.Fatalf("resolver asked %#v, want only the instance's workspace %#v", stub.asked, want)
	}
}

func TestResolveValuesRefusesASecretThatOnlyAnotherWorkspaceHolds(t *testing.T) {
	stub := &workspaceSecretStub{values: map[workspaceSecret]string{{"ws-other", "openai-key"}: "other-value"}}

	got, err := ResolveValues(context.Background(), stub, discardLogger(), "ws-own", "inst-1", map[string]any{
		"API_KEY": map[string]any{"secret_name": "openai-key"},
	})
	if err == nil {
		t.Fatalf("ResolveValues() = %#v, want an error: the secret is not in the instance's workspace", got)
	}
	if got != nil {
		t.Fatalf("ResolveValues() returned values %#v alongside an error", got)
	}
}

func TestResolveValuesFailsOnAResolverError(t *testing.T) {
	stub := &workspaceSecretStub{err: errors.New("secret lookup failed")}

	got, err := ResolveValues(context.Background(), stub, discardLogger(), "ws-own", "inst-1", map[string]any{
		"API_KEY": map[string]any{"secret_name": "openai-key"},
		"PLAIN":   "x",
	})
	if err == nil || got != nil {
		t.Fatalf("ResolveValues() = %#v, %v; want no values and an error", got, err)
	}
}

func TestResolveValuesRefusesAMalformedReference(t *testing.T) {
	stub := &workspaceSecretStub{values: map[workspaceSecret]string{{"ws-own", "k"}: "v"}}
	for name, value := range map[string]any{
		"no secret_name":      map[string]any{"name": "k"},
		"empty secret_name":   map[string]any{"secret_name": ""},
		"numeric secret_name": map[string]any{"secret_name": 3},
		"empty object":        map[string]any{},
	} {
		t.Run(name, func(t *testing.T) {
			got, err := ResolveValues(context.Background(), stub, discardLogger(), "ws-own", "inst-1", map[string]any{"API_KEY": value})
			if err == nil {
				t.Fatalf("ResolveValues() = %#v, want a refusal", got)
			}
		})
	}
	if len(stub.asked) != 0 {
		t.Fatalf("resolver asked %#v for a malformed reference", stub.asked)
	}
}

func TestResolveValuesRefusesAReferenceWithoutWorkspaceOrResolver(t *testing.T) {
	reference := map[string]any{"API_KEY": map[string]any{"secret_name": "openai-key"}}
	stub := &workspaceSecretStub{values: map[workspaceSecret]string{{"", "openai-key"}: "v"}}

	if got, err := ResolveValues(context.Background(), stub, discardLogger(), "", "inst-1", reference); err == nil {
		t.Fatalf("ResolveValues() without a workspace = %#v, want an error", got)
	}
	if len(stub.asked) != 0 {
		t.Fatalf("resolver asked %#v without a workspace", stub.asked)
	}
	if got, err := ResolveValues(context.Background(), nil, discardLogger(), "ws-own", "inst-1", reference); err == nil {
		t.Fatalf("ResolveValues() without a resolver = %#v, want an error", got)
	}
}

func TestResolveValuesPassesLiteralsThroughWithoutAResolver(t *testing.T) {
	got, err := ResolveValues(context.Background(), nil, discardLogger(), "", "inst-1", map[string]any{
		"PLAIN": "x",
		"PORT":  float64(8080),
	})
	if err != nil {
		t.Fatalf("ResolveValues() error = %v", err)
	}
	if want := map[string]string{"PLAIN": "x", "PORT": "8080"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("ResolveValues() = %#v, want %#v", got, want)
	}
}

func TestResolveValuesReadsTheSecretOnEveryCall(t *testing.T) {
	stub := &workspaceSecretStub{values: map[workspaceSecret]string{{"ws-own", "openai-key"}: "before"}}
	values := map[string]any{"API_KEY": map[string]any{"secret_name": "openai-key"}}

	if _, err := ResolveValues(context.Background(), stub, discardLogger(), "ws-own", "inst-1", values); err != nil {
		t.Fatal(err)
	}
	stub.values[workspaceSecret{"ws-own", "openai-key"}] = "rotated"
	got, err := ResolveValues(context.Background(), stub, discardLogger(), "ws-own", "inst-1", values)
	if err != nil {
		t.Fatal(err)
	}
	if got["API_KEY"] != "rotated" {
		t.Fatalf("API_KEY = %q, want the rotated value", got["API_KEY"])
	}
}

func TestResolveValuesLogsTheReferenceButNotTheValue(t *testing.T) {
	const secretValue = "PRIVATE_SECRET_VALUE"
	var logs bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{Level: slog.LevelDebug}))
	stub := &workspaceSecretStub{values: map[workspaceSecret]string{{"ws-own", "openai-key"}: secretValue}}

	if _, err := ResolveValues(context.Background(), stub, logger, "ws-own", "inst-1", map[string]any{
		"API_KEY": map[string]any{"secret_name": "openai-key"},
	}); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"level=INFO", "instance_id=inst-1", "name=API_KEY", "secret_name=openai-key"} {
		if !strings.Contains(logs.String(), want) {
			t.Errorf("logs = %q, want %q", logs.String(), want)
		}
	}
	if strings.Contains(logs.String(), secretValue) {
		t.Fatalf("logs exposed the secret value: %s", logs.String())
	}
}

func TestResolveValuesRefusesAPlatformReservedSecretName(t *testing.T) {
	for _, secretName := range []string{
		"provider_config_x",
		"mcp_instance_11111111-1111-4111-8111-111111111111_API_KEY",
		"mcp_auth_cred:x",
		"channel_cred:x",
		"wallet_creds_x",
		"openapi:x",
		"task-input/x",
		"a2a_push_token:x",
		"task_webhook:x",
	} {
		t.Run(secretName, func(t *testing.T) {
			stub := &workspaceSecretStub{values: map[workspaceSecret]string{{"ws-own", secretName}: "platform-value"}}
			got, err := ResolveValues(context.Background(), stub, discardLogger(), "ws-own", "inst-1", map[string]any{
				"API_KEY": map[string]any{"secret_name": secretName},
			})
			if err == nil {
				t.Fatalf("ResolveValues() = %#v, want a refusal of a platform-reserved name", got)
			}
			if len(stub.asked) != 0 {
				t.Fatalf("resolver asked %#v for a platform-reserved name", stub.asked)
			}
		})
	}
}

func TestResolveValuesRefusesAnEmptySecretValue(t *testing.T) {
	stub := &workspaceSecretStub{values: map[workspaceSecret]string{{"ws-own", "openai-key"}: ""}}

	got, err := ResolveValues(context.Background(), stub, discardLogger(), "ws-own", "inst-1", map[string]any{
		"API_KEY": map[string]any{"secret_name": "openai-key"},
	})
	if err == nil || got != nil {
		t.Fatalf("ResolveValues() = %#v, %v; want no values and an error for an empty secret", got, err)
	}
	for _, want := range []string{"API_KEY", "openai-key"} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("error %q does not name %q", err, want)
		}
	}
}

func TestRefuseReferencesRejectsAReferenceInEitherField(t *testing.T) {
	for field, spec := range map[string]map[string]any{
		"environment.API_KEY":   {"environment": map[string]any{"API_KEY": map[string]any{"secret_name": "PROD_KEY"}, "PLAIN": "x"}},
		"headers.Authorization": {"headers": map[string]any{"Authorization": map[string]any{"secret_name": "PROD_KEY"}}},
	} {
		t.Run(field, func(t *testing.T) {
			err := RefuseReferences("server spec", spec)
			if err == nil {
				t.Fatal("RefuseReferences() error = nil, want a refusal")
			}
			if !strings.Contains(err.Error(), "server spec "+field) {
				t.Fatalf("error %q does not name %q", err, "server spec "+field)
			}
		})
	}
}

func TestRefuseReferencesAcceptsLiterals(t *testing.T) {
	for _, spec := range []map[string]any{
		nil,
		{},
		{"environment": map[string]any{"PLAIN": "x", "PORT": float64(8080)}, "headers": map[string]any{"X-Region": "eu"}},
	} {
		if err := RefuseReferences("server spec", spec); err != nil {
			t.Fatalf("RefuseReferences(%#v) error = %v", spec, err)
		}
	}
}

func TestResolversRefuseAPlatformReservedNameBeforeAnyLookup(t *testing.T) {
	const name = "mcp_instance_11111111-1111-4111-8111-111111111111_API_KEY"
	for resolverName, resolver := range map[string]WorkspaceSecretResolver{
		"database":  &DatabaseSecretResolver{logger: discardLogger()},
		"infisical": &InfisicalSecretResolver{logger: discardLogger()},
	} {
		t.Run(resolverName, func(t *testing.T) {
			_, err := resolver.ResolveWorkspaceSecret(context.Background(), "ws-own", name)
			if err == nil || !strings.Contains(err.Error(), "reserved") {
				t.Fatalf("ResolveWorkspaceSecret() error = %v, want a reserved-name refusal", err)
			}
		})
	}
}
