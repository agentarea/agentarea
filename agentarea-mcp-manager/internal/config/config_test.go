package config

import "testing"

func TestLoadKubernetesConfigPodServiceAccountName(t *testing.T) {
	t.Setenv("KUBERNETES_POD_SERVICE_ACCOUNT_NAME", "agentarea-mcp-runtime")

	cfg := loadKubernetesConfig()

	if cfg.PodServiceAccountName != "agentarea-mcp-runtime" {
		t.Fatalf("PodServiceAccountName = %q, want %q", cfg.PodServiceAccountName, "agentarea-mcp-runtime")
	}
}
