package sandboxruntime

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

func policyEnv(vars map[string]string) map[string]string {
	out := map[string]string{
		"AGENTAREA_SANDBOX_LEASE_TTL":         "2h",
		"AGENTAREA_SANDBOX_IDLE_TTL":          "15m",
		"AGENTAREA_SANDBOX_PROVISION_TIMEOUT": "30s",
		"AGENTAREA_SANDBOX_SESSION_TTL":       "24h",
		"AGENTAREA_SANDBOX_STORAGE":           "s3",
	}
	for k, v := range vars {
		out[k] = v
	}
	return out
}

func loadRuntimeConfig(t *testing.T, provider string, vars map[string]string) (Config, error) {
	t.Helper()
	l := config.FromMap(policyEnv(vars))
	cfg := LoadConfig(l, provider)
	return cfg, l.Err()
}

func newTestRuntime(t *testing.T, provider string, vars map[string]string) (ManagedRuntime, string, error) {
	t.Helper()
	cfg, err := loadRuntimeConfig(t, provider, vars)
	if err != nil {
		t.Fatal(err)
	}
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	return New(nil, client, provider, cfg, testWorkspaceLimits(), http.DefaultTransport)
}

func TestNewSelectsExternalProviderWithoutBuiltinFallback(t *testing.T) {
	runtime, provider, err := newTestRuntime(t, "cube", map[string]string{
		"AGENTAREA_SANDBOX_CUBE_URL":       "https://cube.example",
		"AGENTAREA_SANDBOX_CUBE_API_KEY":   "e2b_test",
		"AGENTAREA_SANDBOX_CUBE_TEMPLATE":  "cube-template",
		"AGENTAREA_SANDBOX_CUBE_ISOLATION": "firecracker",
		"AGENTAREA_SANDBOX_MANIFEST_PATH":  writeManifest(t, testManifest()),
		"AGENTAREA_SANDBOX_ALLOW_INTERNET": "false",
	})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if runtime == nil || provider != "cube" {
		t.Fatalf("runtime=%T provider=%q", runtime, provider)
	}
}

func TestNewSupportsExplicitLocalOpenSandboxMode(t *testing.T) {
	runtime, provider, err := newTestRuntime(t, "opensandbox", map[string]string{
		"AGENTAREA_SANDBOX_OSB_URL":            "http://127.0.0.1:8080",
		"AGENTAREA_SANDBOX_OSB_INSECURE":       "true",
		"AGENTAREA_SANDBOX_OSB_ISOLATION":      "container-dev",
		"AGENTAREA_SANDBOX_OSB_WEAK_ISOLATION": "true",
		"AGENTAREA_SANDBOX_OSB_EGRESS":         "provider",
		"AGENTAREA_SANDBOX_OSB_IMAGE":          "opensandbox/code-interpreter:test",
		"AGENTAREA_SANDBOX_MANIFEST_PATH":      writeManifest(t, testManifest()),
		"AGENTAREA_SANDBOX_ALLOW_INTERNET":     "false",
	})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if runtime == nil || provider != "opensandbox" {
		t.Fatalf("runtime=%T provider=%q", runtime, provider)
	}
}

func TestNewLoadsInlineManifest(t *testing.T) {
	manifest, err := json.Marshal(testManifest())
	if err != nil {
		t.Fatal(err)
	}
	runtime, provider, err := newTestRuntime(t, "e2b", map[string]string{
		"AGENTAREA_SANDBOX_E2B_URL":        "https://api.e2b.app",
		"AGENTAREA_SANDBOX_E2B_API_KEY":    "e2b_test",
		"AGENTAREA_SANDBOX_E2B_TEMPLATE":   "agentarea-runtime",
		"AGENTAREA_SANDBOX_E2B_ISOLATION":  "firecracker",
		"AGENTAREA_SANDBOX_MANIFEST_JSON":  string(manifest),
		"AGENTAREA_SANDBOX_ALLOW_INTERNET": "true",
	})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if runtime == nil || provider != "e2b" {
		t.Fatalf("runtime=%T provider=%q", runtime, provider)
	}
}

func TestNewRejectsUnknownProviderInsteadOfFallingBack(t *testing.T) {
	if _, _, err := newTestRuntime(t, "mystery", nil); err == nil {
		t.Fatal("unknown provider unexpectedly accepted")
	}
}

func TestNewRefusesAnExternalProviderWithoutATransport(t *testing.T) {
	cfg, err := loadRuntimeConfig(t, "e2b", map[string]string{
		"AGENTAREA_SANDBOX_E2B_URL":        "https://api.e2b.app",
		"AGENTAREA_SANDBOX_E2B_API_KEY":    "e2b_test",
		"AGENTAREA_SANDBOX_E2B_TEMPLATE":   "agentarea-runtime",
		"AGENTAREA_SANDBOX_E2B_ISOLATION":  "firecracker",
		"AGENTAREA_SANDBOX_MANIFEST_PATH":  writeManifest(t, testManifest()),
		"AGENTAREA_SANDBOX_ALLOW_INTERNET": "false",
	})
	if err != nil {
		t.Fatal(err)
	}
	client := redis.NewClient(&redis.Options{Addr: miniredis.RunT(t).Addr()})
	t.Cleanup(func() { _ = client.Close() })
	if _, _, err := New(nil, client, "e2b", cfg, testWorkspaceLimits(), nil); err == nil {
		t.Fatal("external provider without an outbound transport unexpectedly built")
	}
}

func TestLoadConfigRejectsSessionRecordTTLShorterThanProviderLease(t *testing.T) {
	_, err := loadRuntimeConfig(t, "", map[string]string{"AGENTAREA_SANDBOX_SESSION_TTL": "1h"})
	if err == nil || !strings.Contains(err.Error(), "AGENTAREA_SANDBOX_SESSION_TTL") {
		t.Fatalf("short provider session record TTL unexpectedly accepted by policy loader: %v", err)
	}
	client := redis.NewClient(&redis.Options{Addr: miniredis.RunT(t).Addr()})
	t.Cleanup(func() { _ = client.Close() })
	if _, _, err := New(nil, client, "e2b", Config{}, testWorkspaceLimits(), http.DefaultTransport); err == nil {
		t.Fatal("short provider session record TTL unexpectedly accepted")
	}
}

func loadPolicy(vars map[string]string) (ControlPolicy, error) {
	l := config.FromMap(vars)
	policy := LoadControlPolicy(l)
	return policy, l.Err()
}

func TestControlPolicyRejectsSessionRecordTTLThatCanExpireBeforeIdleSandbox(t *testing.T) {
	vars := map[string]string{
		"AGENTAREA_SANDBOX_LEASE_TTL":         "30m",
		"AGENTAREA_SANDBOX_IDLE_TTL":          "2h",
		"AGENTAREA_SANDBOX_PROVISION_TIMEOUT": "30s",
	}
	for _, recordTTL := range []string{"90m", "2h"} {
		t.Run(recordTTL, func(t *testing.T) {
			vars["AGENTAREA_SANDBOX_SESSION_TTL"] = recordTTL
			if _, err := loadPolicy(vars); err == nil {
				t.Fatalf("session record TTL %s unexpectedly accepted", recordTTL)
			}
		})
	}
	vars["AGENTAREA_SANDBOX_SESSION_TTL"] = "2h1s"
	if _, err := loadPolicy(vars); err != nil {
		t.Fatalf("session record outliving idle sandbox rejected: %v", err)
	}
}

func TestControlPolicyRequiresProvisioningIntentToOutliveCreateAndLease(t *testing.T) {
	vars := map[string]string{
		"AGENTAREA_SANDBOX_LEASE_TTL":         "30m",
		"AGENTAREA_SANDBOX_IDLE_TTL":          "15m",
		"AGENTAREA_SANDBOX_PROVISION_TIMEOUT": "30s",
		"AGENTAREA_SANDBOX_SESSION_TTL":       "30m30s",
	}
	if _, err := loadPolicy(vars); err == nil {
		t.Fatal("session record expiring with the last possible remote lease unexpectedly accepted")
	}
	vars["AGENTAREA_SANDBOX_SESSION_TTL"] = "30m31s"
	if _, err := loadPolicy(vars); err != nil {
		t.Fatalf("session record outliving create and lease rejected: %v", err)
	}
}

func TestLoadControlPolicyRequiresExplicitValues(t *testing.T) {
	_, err := loadPolicy(nil)
	if err == nil {
		t.Fatal("missing sandbox control policy unexpectedly accepted")
	}
	for _, name := range []string{"AGENTAREA_SANDBOX_LEASE_TTL", "AGENTAREA_SANDBOX_IDLE_TTL", "AGENTAREA_SANDBOX_PROVISION_TIMEOUT", "AGENTAREA_SANDBOX_SESSION_TTL"} {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("error does not name %s: %v", name, err)
		}
	}
}

func TestLoadControlPolicyAcceptsAZeroIdleTTLOnly(t *testing.T) {
	vars := policyEnv(map[string]string{"AGENTAREA_SANDBOX_IDLE_TTL": "0s"})
	if _, err := loadPolicy(vars); err != nil {
		t.Fatalf("zero idle TTL rejected: %v", err)
	}
	vars["AGENTAREA_SANDBOX_LEASE_TTL"] = "0s"
	if _, err := loadPolicy(vars); err == nil {
		t.Fatal("zero lease TTL unexpectedly accepted")
	}
}

func testWorkspaceLimits() WorkspaceLimits {
	return WorkspaceLimits{MaxFiles: 1000, MaxFileBytes: 256 * 1024 * 1024, MaxBytes: 2 * 1024 * 1024 * 1024}
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

func TestLoadConfigRequiresExplicitInternetPolicy(t *testing.T) {
	_, err := loadRuntimeConfig(t, "e2b", map[string]string{
		"AGENTAREA_SANDBOX_E2B_URL":       "https://api.e2b.app",
		"AGENTAREA_SANDBOX_E2B_API_KEY":   "e2b_test",
		"AGENTAREA_SANDBOX_E2B_TEMPLATE":  "agentarea-runtime",
		"AGENTAREA_SANDBOX_E2B_ISOLATION": "firecracker",
		"AGENTAREA_SANDBOX_MANIFEST_PATH": writeManifest(t, testManifest()),
	})
	if err == nil || !strings.Contains(err.Error(), "AGENTAREA_SANDBOX_ALLOW_INTERNET") {
		t.Fatalf("missing sandbox internet policy unexpectedly accepted: %v", err)
	}
}

func TestLoadConfigReadsNoExternalProviderForABuiltin(t *testing.T) {
	if _, err := loadRuntimeConfig(t, "", nil); err != nil {
		t.Fatalf("built-in provider needed external configuration: %v", err)
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

func TestLoadWorkspaceProviderIsRequiredAndClosed(t *testing.T) {
	for _, value := range []string{"", "gcs"} {
		l := config.FromMap(map[string]string{"AGENTAREA_SANDBOX_STORAGE": value})
		LoadWorkspaceProvider(l)
		if l.Err() == nil {
			t.Fatalf("workspace provider %q unexpectedly resolved", value)
		}
	}
	l := config.FromMap(map[string]string{"AGENTAREA_SANDBOX_STORAGE": "s3"})
	if provider := LoadWorkspaceProvider(l); l.Err() != nil || provider != WorkspaceProviderS3 {
		t.Fatalf("LoadWorkspaceProvider() = %q, %v", provider, l.Err())
	}
}

func TestWorkspaceRuntimeFactoryRefusesAnUnresolvedProvider(t *testing.T) {
	if _, err := NewWorkspaceRuntimeForProvider(nil, WorkspaceProvider(""), nil, http.DefaultTransport); err == nil {
		t.Fatal("unresolved workspace provider unexpectedly built a runtime")
	}
}
