package app

import (
	"bytes"
	"context"
	"errors"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/ext"
)

func quiet(opts ...ext.Option) (*Build, *bytes.Buffer) {
	b := Default(opts...)
	var out bytes.Buffer
	b.stdout, b.stderr = &out, &out
	b.lookup = func(string) (string, bool) { return "", false }
	return b, &out
}

func TestNoRoleIsUsage(t *testing.T) {
	b, out := quiet()
	err := b.Run(context.Background(), nil)
	if !errors.Is(err, ErrUsage) || b.exitCode(err) != 2 {
		t.Fatalf("got %v", err)
	}
	for _, r := range roles() {
		if !strings.Contains(out.String(), r.name) {
			t.Errorf("usage does not list %s", r.name)
		}
	}
}

func TestUnknownRoleIsUsage(t *testing.T) {
	b, _ := quiet()
	if err := b.Run(context.Background(), []string{"bogus"}); !errors.Is(err, ErrUsage) {
		t.Fatalf("got %v", err)
	}
}

func TestEveryUnportedRoleSaysNotImplemented(t *testing.T) {
	want := []string{"serve", "worker", "events", "mcp", "sandbox", "operator", "runner", "all", "migrate", "openapi"}
	var names []string
	for _, r := range roles() {
		names = append(names, r.name)
	}
	if !slices.Equal(names, want) {
		t.Fatalf("role table %v", names)
	}
	for _, name := range want {
		if name == "serve" || name == "migrate" || name == "worker" || name == "mcp" || name == "events" || name == "all" {
			continue
		}
		b, _ := quiet()
		err := b.Run(context.Background(), []string{name})
		if !errors.Is(err, ErrNotImplemented) || b.exitCode(err) != 1 {
			t.Errorf("%s: got %v", name, err)
		}
	}
}

func TestExtensionCommandRuns(t *testing.T) {
	var got []string
	b, _ := quiet(ext.WithCommand(ext.Command{Name: "rollup", Run: func(_ context.Context, d ext.Deps, args []string) error {
		if d.Logger == nil || d.Config == nil || d.DB == nil {
			return errors.New("deps missing")
		}
		got = args
		return nil
	}}))
	b.lookup = mapLookup(dbVars)
	if err := b.Run(context.Background(), []string{"rollup", "--since", "1d"}); err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(got, []string{"--since", "1d"}) {
		t.Fatalf("args %v", got)
	}
}

func TestExtensionShadowingACoreRoleIsRefused(t *testing.T) {
	b, _ := quiet(ext.WithRole(ext.Role{Name: "worker", Run: func(context.Context, ext.Deps) error { return nil }}))
	err := b.Run(context.Background(), []string{"worker"})
	if err == nil || !strings.Contains(err.Error(), "shadows a core role") {
		t.Fatalf("got %v", err)
	}
}

func TestInvalidExtensionSetIsRefused(t *testing.T) {
	b, _ := quiet(ext.WithToolBilling(nil))
	if err := b.Run(context.Background(), []string{"serve"}); err == nil || errors.Is(err, ErrNotImplemented) {
		t.Fatalf("got %v", err)
	}
}

func TestServeRefusesABadPort(t *testing.T) {
	b, _ := quiet()
	b.lookup = mapLookup(map[string]string{"PORT": "70000"})
	err := b.Run(context.Background(), []string{"serve"})
	if err == nil || errors.Is(err, ErrNotImplemented) || b.exitCode(err) != 1 || !strings.Contains(err.Error(), "PORT") {
		t.Fatalf("got %v", err)
	}
}

func TestServeRunsUntilCancelled(t *testing.T) {
	t.Setenv("TEMPORAL_ADDRESS", "127.0.0.1:1")
	t.Setenv("TEMPORAL_NAMESPACE", "default")
	b, _ := quiet()
	vars := map[string]string{"HOST": "127.0.0.1", "PORT": "0"}
	for k, v := range serveVars {
		vars[k] = v
	}
	b.lookup = mapLookup(vars)
	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	if err := b.Run(ctx, []string{"serve"}); err != nil {
		t.Fatal(err)
	}
}

// dbVars name a database nobody listens on; pools connect on first use.
var dbVars = map[string]string{
	"AGENTAREA_DB_HOST": "127.0.0.1", "AGENTAREA_DB_PORT": "1", "AGENTAREA_DB_NAME": "x",
	"AGENTAREA_DB_USER": "x", "AGENTAREA_DB_PASSWORD": "x",
}

// serveVars configure the cluster profile against nothing that listens;
// no adapter dials before the first request.
var serveVars = map[string]string{
	"AGENTAREA_DB_HOST": "127.0.0.1", "AGENTAREA_DB_PORT": "1", "AGENTAREA_DB_NAME": "x",
	"AGENTAREA_DB_USER": "x", "AGENTAREA_DB_PASSWORD": "x",
	"AGENTAREA_REDIS_URL": "redis://127.0.0.1:1", "AGENTAREA_AUTHZ_FGA_STORE_ID": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
	"AGENTAREA_SECRET_ENCRYPTION_KEY": "dGhpcyBpcyBhIDMyIGJ5dGUga2V5IGZvciB0ZXN0cyE=",
	"AGENTAREA_S3_ACCESS_KEY":         "x", "AGENTAREA_S3_SECRET_KEY": "x",
	"AGENTAREA_AUTH_JWKS_B64":  "eyJrZXlzIjpbXX0=",
	"AGENTAREA_TEMPORAL_QUEUE": "agentarea", "AGENTAREA_TRIGGER_QUEUE": "agentarea-triggers",
	"AGENTAREA_MCP_BACKEND": "docker", "AGENTAREA_MCP_GATEWAY_SECRET": "app-test-gateway-secret-0123456789abcdef",
	"AGENTAREA_MCP_LEASE_TTL": "30s", "AGENTAREA_MCP_STARTUP_TIMEOUT": "60s",
	"AGENTAREA_MCP_IDLE_TIMEOUT": "0", "AGENTAREA_MCP_SWEEP_INTERVAL": "30s",
}

func mapLookup(vars map[string]string) func(string) (string, bool) {
	return func(name string) (string, bool) {
		v, ok := vars[name]
		return v, ok
	}
}
