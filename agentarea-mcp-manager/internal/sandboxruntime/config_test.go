package sandboxruntime

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/go-redis/redis/v8"
)

func TestNewFromEnvSelectsExternalProviderWithoutLegacyFallback(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	manifestPath := writeManifest(t, testManifest(true))

	t.Setenv("SANDBOX_PROVIDER", "cube")
	t.Setenv("SANDBOX_CUBE_API_URL", "https://cube.example")
	t.Setenv("SANDBOX_CUBE_API_KEY", "e2b_test")
	t.Setenv("SANDBOX_CUBE_TEMPLATE_ALLOWED", "cube-template")
	t.Setenv("SANDBOX_RUNTIME_MANIFEST_ALLOWED_PATH", manifestPath)

	runtime, provider, err := NewFromEnv(context.Background(), nil, client, "kubernetes")
	if err != nil {
		t.Fatalf("NewFromEnv() error = %v", err)
	}
	if runtime == nil || provider != "cube" {
		t.Fatalf("runtime=%T provider=%q", runtime, provider)
	}
}

func TestNewFromEnvSupportsExplicitLocalOpenSandboxMode(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })

	t.Setenv("SANDBOX_PROVIDER", "opensandbox")
	t.Setenv("SANDBOX_OPENSANDBOX_URL", "http://127.0.0.1:8080")
	t.Setenv("SANDBOX_OPENSANDBOX_ALLOW_INSECURE", "true")
	t.Setenv("SANDBOX_OPENSANDBOX_ISOLATION", "container-dev")
	t.Setenv("SANDBOX_OPENSANDBOX_ALLOW_WEAK_ISOLATION_FOR_DEVELOPMENT", "true")
	t.Setenv("SANDBOX_OPENSANDBOX_EGRESS_MODE", "provider")
	t.Setenv("SANDBOX_OPENSANDBOX_IMAGE_ALLOWED", "opensandbox/code-interpreter:test")
	t.Setenv("SANDBOX_RUNTIME_MANIFEST_ALLOWED_PATH", writeManifest(t, testManifest(true)))

	runtime, provider, err := NewFromEnv(context.Background(), nil, client, "kubernetes")
	if err != nil {
		t.Fatalf("NewFromEnv() error = %v", err)
	}
	if runtime == nil || provider != "opensandbox" {
		t.Fatalf("runtime=%T provider=%q", runtime, provider)
	}
}

func TestNewFromEnvLoadsInlineManifest(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	manifest, err := json.Marshal(testManifest(true))
	if err != nil {
		t.Fatal(err)
	}

	t.Setenv("SANDBOX_PROVIDER", "e2b")
	t.Setenv("SANDBOX_E2B_API_URL", "https://api.e2b.app")
	t.Setenv("SANDBOX_E2B_API_KEY", "e2b_test")
	t.Setenv("SANDBOX_E2B_TEMPLATE_ALLOWED", "agentarea-allowed")
	t.Setenv("SANDBOX_RUNTIME_MANIFEST_ALLOWED_JSON", string(manifest))

	runtime, provider, err := NewFromEnv(context.Background(), nil, client, "kubernetes")
	if err != nil {
		t.Fatalf("NewFromEnv() error = %v", err)
	}
	if runtime == nil || provider != "e2b" {
		t.Fatalf("runtime=%T provider=%q", runtime, provider)
	}
}

func TestNewFromEnvRejectsUnknownProviderInsteadOfFallingBack(t *testing.T) {
	t.Setenv("SANDBOX_PROVIDER", "mystery")
	_, _, err := NewFromEnv(context.Background(), nil, nil, "kubernetes")
	if err == nil {
		t.Fatal("unknown provider unexpectedly accepted")
	}
}

func TestNewFromEnvRejectsSessionRecordTTLShorterThanProviderLease(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	t.Setenv("SANDBOX_PROVIDER", "e2b")
	t.Setenv("SANDBOX_TASK_LEASE_TTL", "2h")
	t.Setenv("SANDBOX_PROVIDER_SESSION_TTL", "1h")

	if _, _, err := NewFromEnv(context.Background(), nil, client, "kubernetes"); err == nil {
		t.Fatal("short provider session record TTL unexpectedly accepted")
	}
}

func TestNewManagerRequiresPositiveLeaseTTL(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	store, _ := NewSessionStore(client, "test", time.Hour)
	if _, err := NewManager(&fakeExternalProvider{}, store, 0, nil); err == nil {
		t.Fatal("zero idle TTL unexpectedly accepted")
	}
}

func writeManifest(t *testing.T, manifest any) string {
	t.Helper()
	data, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	filePath := filepath.Join(t.TempDir(), "runtime.json")
	if err := os.WriteFile(filePath, data, 0o600); err != nil {
		t.Fatal(err)
	}
	return filePath
}
