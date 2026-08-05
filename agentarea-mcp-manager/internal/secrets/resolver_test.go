package secrets

import (
	"bytes"
	"context"
	"database/sql"
	"database/sql/driver"
	"errors"
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
	if err.Error() != "failed to resolve requested environment variable" {
		t.Fatalf("ResolveInstanceEnvVars() error = %q, want the fixed redacted message", err)
	}
	if strings.Contains(err.Error(), "PRIVATE_SECRET_KEY") {
		t.Fatalf("ResolveInstanceEnvVars() exposed secret identifier: %q", err)
	}
	if strings.Contains(logs.String(), "PRIVATE_SECRET_KEY") {
		t.Fatalf("resolver logs exposed secret identifier: %s", logs.String())
	}
}

// failingConnector fails on connect so the resolver exercises its real query
// path without a database, and carries a canary the resolver must not surface.
type failingConnector struct{ canary string }

func (c failingConnector) Connect(context.Context) (driver.Conn, error) {
	return nil, errors.New(c.canary)
}

func (c failingConnector) Driver() driver.Driver { return nil }

func newDatabaseResolverWithFailingDB(
	logs *bytes.Buffer, canary string,
) *DatabaseSecretResolver {
	return &DatabaseSecretResolver{
		db:     sql.OpenDB(failingConnector{canary: canary}),
		logger: slog.New(slog.NewTextHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug})),
	}
}

func TestDatabaseResolveInstanceEnvVarsHidesSecretIdentifiers(t *testing.T) {
	const (
		envName = "PRIVATE_SECRET_KEY"
		canary  = "dsn=postgres://user:PRIVATE_DB_PASSWORD@host/db"
	)

	var logs bytes.Buffer
	resolver := newDatabaseResolverWithFailingDB(&logs, canary)
	defer resolver.db.Close()

	_, err := resolver.ResolveInstanceEnvVars("instance-1", []string{envName})
	if err == nil {
		t.Fatal("ResolveInstanceEnvVars() error = nil, want error for unreachable database")
	}
	if err.Error() != "failed to resolve requested environment variable" {
		t.Fatalf("ResolveInstanceEnvVars() error = %q, want the fixed redacted message", err)
	}
	for name, value := range map[string]string{"error": err.Error(), "logs": logs.String()} {
		if strings.Contains(value, envName) {
			t.Fatalf("%s exposed secret identifier: %s", name, value)
		}
		if strings.Contains(value, canary) {
			t.Fatalf("%s exposed database error text: %s", name, value)
		}
	}
}

func TestDatabaseResolveSecretsHidesSecretIdentifiers(t *testing.T) {
	const (
		envName = "PRIVATE_SECRET_KEY"
		canary  = "dsn=postgres://user:PRIVATE_DB_PASSWORD@host/db"
	)

	var logs bytes.Buffer
	resolver := newDatabaseResolverWithFailingDB(&logs, canary)
	defer resolver.db.Close()

	_, err := resolver.ResolveSecrets("instance-1", map[string]string{
		envName:      "secret_ref:" + envName,
		"PLAIN_ONLY": "plain-value",
	})
	if err == nil {
		t.Fatal("ResolveSecrets() error = nil, want error for unreachable database")
	}
	if err.Error() != "failed to resolve secrets for instance" {
		t.Fatalf("ResolveSecrets() error = %q, want the fixed redacted message", err)
	}
	for name, value := range map[string]string{"error": err.Error(), "logs": logs.String()} {
		if strings.Contains(value, envName) {
			t.Fatalf("%s exposed secret identifier: %s", name, value)
		}
		if strings.Contains(value, canary) {
			t.Fatalf("%s exposed database error text: %s", name, value)
		}
	}
}
