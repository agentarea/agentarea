package secrets

import (
	"bytes"
	"log/slog"
	"strings"
	"testing"
)

func TestResolveSecretDoesNotExposeSecretIdentifier(t *testing.T) {
	const secretKey = "PRIVATE_SECRET_KEY"

	var logs bytes.Buffer
	resolver := &InfisicalSecretResolver{
		logger: slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{Level: slog.LevelDebug})),
	}

	_, err := resolver.resolveSecretFromInfisical("instance-1", secretKey)
	if err == nil {
		t.Fatal("resolveSecretFromInfisical() error = nil, want error for uninitialized client")
	}
	if strings.Contains(err.Error(), secretKey) {
		t.Fatalf("resolveSecretFromInfisical() error exposed secret identifier: %q", err)
	}
	if strings.Contains(logs.String(), secretKey) {
		t.Fatalf("resolver logs exposed secret identifier: %s", logs.String())
	}
}

func TestResolveInstanceEnvVarsDoesNotExposeNestedError(t *testing.T) {
	var logs bytes.Buffer
	resolver := &InfisicalSecretResolver{
		logger: slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{Level: slog.LevelDebug})),
	}

	_, err := resolver.ResolveInstanceEnvVars("instance-1", []string{"PRIVATE_SECRET_KEY"})
	if err == nil {
		t.Fatal("ResolveInstanceEnvVars() error = nil, want error for uninitialized client")
	}
	if strings.Contains(err.Error(), "infisical client not initialized") {
		t.Fatalf("ResolveInstanceEnvVars() exposed nested error: %q", err)
	}
	if strings.Contains(err.Error(), "PRIVATE_SECRET_KEY") {
		t.Fatalf("ResolveInstanceEnvVars() exposed secret identifier: %q", err)
	}
	if strings.Contains(logs.String(), "PRIVATE_SECRET_KEY") {
		t.Fatalf("resolver logs exposed secret identifier: %s", logs.String())
	}
}
