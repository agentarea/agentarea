package dataplaneconnect

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadConfigRejectsUnknownJSONFields(t *testing.T) {
	path := filepath.Join(t.TempDir(), "agent.json")
	if err := os.WriteFile(path, []byte(`{"control_plane_url":"https://control.test","data_plane_id":"dp","connector_instance_id":"ci","identity_file":"identity","unknown":true}`), 0600); err != nil {
		t.Fatal(err)
	}
	_, err := LoadConfig([]string{"--config", path})
	if err == nil || !strings.Contains(err.Error(), "unknown field") {
		t.Fatalf("want strict config error, got %v", err)
	}
}

func TestLoadConfigFlagCanDisableInsecureJSON(t *testing.T) {
	path := filepath.Join(t.TempDir(), "agent.json")
	identity := filepath.Join(t.TempDir(), "identity")
	json := `{"control_plane_url":"https://control.test","data_plane_id":"d1f74c88-cc04-4cc7-b4e3-6054901d572a","connector_instance_id":"ci","identity_file":"` + identity + `","allow_insecure_development":true}`
	if err := os.WriteFile(path, []byte(json), 0600); err != nil {
		t.Fatal(err)
	}
	cfg, err := LoadConfig([]string{"--config", path, "--allow-insecure-development=false"})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.AllowInsecureDevelopment {
		t.Fatal("explicit false flag did not override JSON")
	}
}

func TestLoadConfigRejectsInvalidInsecureEnvironmentValue(t *testing.T) {
	t.Setenv("DATA_PLANE_AGENT_ALLOW_INSECURE_DEVELOPMENT", "definitely")
	_, err := LoadConfig([]string{"--control-plane-url", "https://control.test"})
	if err == nil || !strings.Contains(err.Error(), "DATA_PLANE_AGENT_ALLOW_INSECURE_DEVELOPMENT") {
		t.Fatalf("want invalid environment error, got %v", err)
	}
}

func TestLoadConfigRejectsRelativeIdentityFile(t *testing.T) {
	_, err := LoadConfig([]string{"--control-plane-url", "https://control.test", "--identity-file", "identity.json"})
	if err == nil || !strings.Contains(err.Error(), "absolute") {
		t.Fatalf("want absolute identity path error, got %v", err)
	}
}

func TestDefaultProvidersAreDisabledAndCapabilitiesAreNotAdvertised(t *testing.T) {
	cfg, err := LoadConfig([]string{"--control-plane-url", "https://control.test"})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.MCPProvider != "disabled" || cfg.SandboxProvider != "disabled" || cfg.Capabilities.MCP || cfg.Capabilities.Sandbox {
		t.Fatalf("unexpected defaults: %#v", cfg)
	}
}

func TestLoadConfigRejectsAdvertisedButUnconfiguredCapability(t *testing.T) {
	path := filepath.Join(t.TempDir(), "agent.json")
	identity := filepath.Join(t.TempDir(), "identity.json")
	json := `{"control_plane_url":"https://control.test","identity_file":"` + identity + `","capabilities":{"mcp":true}}`
	if err := os.WriteFile(path, []byte(json), 0600); err != nil {
		t.Fatal(err)
	}
	_, err := LoadConfig([]string{"--config", path})
	if err == nil || !strings.Contains(err.Error(), "advertised") {
		t.Fatalf("want fail-closed capability error, got %v", err)
	}
}

func TestLoadConfigRequiresNamespaceForKubernetesProvider(t *testing.T) {
	_, err := LoadConfig([]string{"--control-plane-url", "https://control.test", "--mcp-provider", "kubernetes"})
	if err == nil || !strings.Contains(err.Error(), "kubernetes_namespace") {
		t.Fatalf("want Kubernetes namespace error, got %v", err)
	}
}

func TestLoadConfigValidatesConnectorGatewayURL(t *testing.T) {
	_, err := LoadConfig([]string{"--control-plane-url", "https://control.test", "--connector-gateway-url", "http://gateway.test"})
	if err == nil || !strings.Contains(err.Error(), "connector_gateway_url must use HTTPS") {
		t.Fatalf("want gateway HTTPS error, got %v", err)
	}
}

func TestLoadConfigAllowsExplicitLoopbackHTTPForDevelopment(t *testing.T) {
	cfg, err := LoadConfig([]string{
		"--control-plane-url", "http://127.0.0.1:18000",
		"--connector-gateway-url", "http://localhost:17999",
		"--allow-insecure-development",
	})
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.AllowInsecureDevelopment {
		t.Fatal("explicit development mode was not retained")
	}
}

func TestLoadConfigRejectsRemoteHTTPEvenInDevelopmentMode(t *testing.T) {
	_, err := LoadConfig([]string{
		"--control-plane-url", "http://control.example",
		"--allow-insecure-development",
	})
	if err == nil || !strings.Contains(err.Error(), "limited to loopback") {
		t.Fatalf("want loopback-only HTTP error, got %v", err)
	}
}

func TestLoadConfigAllowsIndependentDockerAndSandboxProviders(t *testing.T) {
	cfg, err := LoadConfig([]string{"--control-plane-url", "https://control.test", "--mcp-provider", "docker", "--sandbox-provider", "kubernetes", "--kubernetes-namespace", "execution"})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.MCPProvider != "docker" || cfg.SandboxProvider != "kubernetes" {
		t.Fatalf("providers = %q, %q", cfg.MCPProvider, cfg.SandboxProvider)
	}
}
