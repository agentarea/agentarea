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

	"github.com/agentarea/mcp-manager/internal/workspace"
)

func TestNewFromEnvSelectsExternalProviderWithoutBuiltinFallback(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	manifestPath := writeManifest(t, testManifest())

	t.Setenv("AGENTAREA_SBX_PROVIDER", "cube")
	t.Setenv("AGENTAREA_SBX_CUBE_URL", "https://cube.example")
	t.Setenv("AGENTAREA_SBX_CUBE_API_KEY", "e2b_test")
	t.Setenv("AGENTAREA_SBX_CUBE_TEMPLATE", "cube-template")
	t.Setenv("AGENTAREA_SBX_CUBE_ISOLATION", "firecracker")
	t.Setenv("AGENTAREA_SBX_MANIFEST_PATH", manifestPath)
	t.Setenv("AGENTAREA_SBX_ALLOW_INTERNET", "false")

	runtime, provider, err := NewFromEnv(context.Background(), nil, client, "kubernetes", mustControlPolicy(t), testWorkspaceLimits())
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

	t.Setenv("AGENTAREA_SBX_PROVIDER", "opensandbox")
	t.Setenv("AGENTAREA_SBX_OSB_URL", "http://127.0.0.1:8080")
	t.Setenv("AGENTAREA_SBX_OSB_INSECURE", "true")
	t.Setenv("AGENTAREA_SBX_OSB_ISOLATION", "container-dev")
	t.Setenv("AGENTAREA_SBX_OSB_WEAK_ISOLATION", "true")
	t.Setenv("AGENTAREA_SBX_OSB_EGRESS", "provider")
	t.Setenv("AGENTAREA_SBX_OSB_IMAGE", "opensandbox/code-interpreter:test")
	t.Setenv("AGENTAREA_SBX_MANIFEST_PATH", writeManifest(t, testManifest()))
	t.Setenv("AGENTAREA_SBX_ALLOW_INTERNET", "false")

	runtime, provider, err := NewFromEnv(context.Background(), nil, client, "kubernetes", mustControlPolicy(t), testWorkspaceLimits())
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
	manifest, err := json.Marshal(testManifest())
	if err != nil {
		t.Fatal(err)
	}

	t.Setenv("AGENTAREA_SBX_PROVIDER", "e2b")
	t.Setenv("AGENTAREA_SBX_E2B_URL", "https://api.e2b.app")
	t.Setenv("AGENTAREA_SBX_E2B_API_KEY", "e2b_test")
	t.Setenv("AGENTAREA_SBX_E2B_TEMPLATE", "agentarea-runtime")
	t.Setenv("AGENTAREA_SBX_E2B_ISOLATION", "firecracker")
	t.Setenv("AGENTAREA_SBX_MANIFEST_JSON", string(manifest))
	t.Setenv("AGENTAREA_SBX_ALLOW_INTERNET", "true")

	runtime, provider, err := NewFromEnv(context.Background(), nil, client, "kubernetes", mustControlPolicy(t), testWorkspaceLimits())
	if err != nil {
		t.Fatalf("NewFromEnv() error = %v", err)
	}
	if runtime == nil || provider != "e2b" {
		t.Fatalf("runtime=%T provider=%q", runtime, provider)
	}
}

func TestNewFromEnvRejectsUnknownProviderInsteadOfFallingBack(t *testing.T) {
	t.Setenv("AGENTAREA_SBX_PROVIDER", "mystery")
	_, _, err := NewFromEnv(context.Background(), nil, nil, "kubernetes", mustControlPolicy(t), testWorkspaceLimits())
	if err == nil {
		t.Fatal("unknown provider unexpectedly accepted")
	}
}

func TestNewFromEnvRejectsSessionRecordTTLShorterThanProviderLease(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	t.Setenv("AGENTAREA_SBX_PROVIDER", "e2b")
	t.Setenv("AGENTAREA_SBX_LEASE_TTL", "2h")
	t.Setenv("AGENTAREA_SBX_IDLE_TTL", "15m")
	t.Setenv("AGENTAREA_SBX_PROVISION_TIMEOUT", "30s")
	t.Setenv("AGENTAREA_SBX_SESSION_TTL", "1h")

	if _, err := LoadControlPolicyFromEnv(); err == nil {
		t.Fatal("short provider session record TTL unexpectedly accepted by policy loader")
	}
	if _, _, err := NewFromEnv(context.Background(), nil, client, "kubernetes", ControlPolicy{}, testWorkspaceLimits()); err == nil {
		t.Fatal("short provider session record TTL unexpectedly accepted")
	}
}

func TestControlPolicyRejectsSessionRecordTTLThatCanExpireBeforeIdleSandbox(t *testing.T) {
	t.Setenv("AGENTAREA_SBX_LEASE_TTL", "30m")
	t.Setenv("AGENTAREA_SBX_IDLE_TTL", "2h")
	t.Setenv("AGENTAREA_SBX_PROVISION_TIMEOUT", "30s")
	for _, recordTTL := range []string{"90m", "2h"} {
		t.Run(recordTTL, func(t *testing.T) {
			t.Setenv("AGENTAREA_SBX_SESSION_TTL", recordTTL)
			if _, err := LoadControlPolicyFromEnv(); err == nil {
				t.Fatalf("session record TTL %s unexpectedly accepted", recordTTL)
			}
		})
	}
	t.Setenv("AGENTAREA_SBX_SESSION_TTL", "2h1s")
	if _, err := LoadControlPolicyFromEnv(); err != nil {
		t.Fatalf("session record outliving idle sandbox rejected: %v", err)
	}
}

func TestControlPolicyRequiresProvisioningIntentToOutliveCreateAndLease(t *testing.T) {
	t.Setenv("AGENTAREA_SBX_LEASE_TTL", "30m")
	t.Setenv("AGENTAREA_SBX_IDLE_TTL", "15m")
	t.Setenv("AGENTAREA_SBX_PROVISION_TIMEOUT", "30s")
	t.Setenv("AGENTAREA_SBX_SESSION_TTL", "30m30s")
	if _, err := LoadControlPolicyFromEnv(); err == nil {
		t.Fatal("session record expiring with the last possible remote lease unexpectedly accepted")
	}
	t.Setenv("AGENTAREA_SBX_SESSION_TTL", "30m31s")
	if _, err := LoadControlPolicyFromEnv(); err != nil {
		t.Fatalf("session record outliving create and lease rejected: %v", err)
	}
}

func TestLoadControlPolicyRequiresExplicitValues(t *testing.T) {
	t.Setenv("AGENTAREA_SBX_LEASE_TTL", "")
	t.Setenv("AGENTAREA_SBX_IDLE_TTL", "")
	t.Setenv("AGENTAREA_SBX_PROVISION_TIMEOUT", "")
	t.Setenv("AGENTAREA_SBX_SESSION_TTL", "")

	if _, err := LoadControlPolicyFromEnv(); err == nil {
		t.Fatal("missing sandbox control policy unexpectedly accepted")
	}
}

func testWorkspaceLimits() WorkspaceLimits {
	return WorkspaceLimits{MaxFiles: 1000, MaxFileBytes: 256 * 1024 * 1024, MaxBytes: 2 * 1024 * 1024 * 1024}
}

func mustControlPolicy(t *testing.T) ControlPolicy {
	t.Helper()
	t.Setenv("AGENTAREA_SBX_LEASE_TTL", "2h")
	t.Setenv("AGENTAREA_SBX_IDLE_TTL", "15m")
	t.Setenv("AGENTAREA_SBX_PROVISION_TIMEOUT", "30s")
	t.Setenv("AGENTAREA_SBX_SESSION_TTL", "24h")
	policy, err := LoadControlPolicyFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	return policy
}

func TestNewManagerRequiresPositiveLeaseTTL(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	store, _ := NewSessionStore(client, "test", time.Hour)
	if _, err := NewManager(&fakeExternalProvider{}, store, 0, time.Minute, nil, testWorkspaceLimits()); err == nil {
		t.Fatal("zero idle TTL unexpectedly accepted")
	}
}

func TestNewFromEnvRequiresExplicitInternetPolicy(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	t.Setenv("AGENTAREA_SBX_PROVIDER", "e2b")
	t.Setenv("AGENTAREA_SBX_E2B_URL", "https://api.e2b.app")
	t.Setenv("AGENTAREA_SBX_E2B_API_KEY", "e2b_test")
	t.Setenv("AGENTAREA_SBX_E2B_TEMPLATE", "agentarea-runtime")
	t.Setenv("AGENTAREA_SBX_E2B_ISOLATION", "firecracker")
	t.Setenv("AGENTAREA_SBX_MANIFEST_PATH", writeManifest(t, testManifest()))
	t.Setenv("AGENTAREA_SBX_ALLOW_INTERNET", "")

	if _, _, err := NewFromEnv(context.Background(), nil, client, "kubernetes", mustControlPolicy(t), testWorkspaceLimits()); err == nil {
		t.Fatal("missing sandbox internet policy unexpectedly accepted")
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

func TestLoadWorkspaceProviderFromEnvIsRequiredAndClosed(t *testing.T) {
	t.Setenv("AGENTAREA_SBX_STORAGE", "")
	if _, err := LoadWorkspaceProviderFromEnv(); err == nil {
		t.Fatal("missing workspace provider unexpectedly resolved")
	}
	t.Setenv("AGENTAREA_SBX_STORAGE", "gcs")
	if _, err := LoadWorkspaceProviderFromEnv(); err == nil {
		t.Fatal("unsupported workspace provider unexpectedly resolved")
	}
	t.Setenv("AGENTAREA_SBX_STORAGE", "s3")
	provider, err := LoadWorkspaceProviderFromEnv()
	if err != nil || provider != WorkspaceProviderS3 {
		t.Fatalf("LoadWorkspaceProviderFromEnv() = %q, %v", provider, err)
	}
}

// The decorator must not re-read process state: an unresolved provider value
// fails here rather than silently picking one up from the environment.
func TestWorkspaceRuntimeFactoryIgnoresProcessEnvironment(t *testing.T) {
	t.Setenv("AGENTAREA_SBX_STORAGE", "s3")
	if _, err := NewWorkspaceRuntimeForProvider(context.Background(), nil, WorkspaceProvider(""), workspace.RepositoryConfig{}); err == nil {
		t.Fatal("unresolved workspace provider unexpectedly built a runtime")
	}
}
