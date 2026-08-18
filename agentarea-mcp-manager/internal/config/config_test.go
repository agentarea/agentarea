package config

import "testing"

func TestLoadKubernetesConfigPodServiceAccountName(t *testing.T) {
	t.Setenv("KUBERNETES_POD_SERVICE_ACCOUNT_NAME", "agentarea-mcp-runtime")

	cfg := loadKubernetesConfig()

	if cfg.PodServiceAccountName != "agentarea-mcp-runtime" {
		t.Fatalf("PodServiceAccountName = %q, want %q", cfg.PodServiceAccountName, "agentarea-mcp-runtime")
	}
}

// TestLoadInstancePodFromEnv locks the chart->manager contract: the JSON the
// Helm chart emits for KUBERNETES_INSTANCE_POD (toJson of mcpManager.instancePod)
// must parse into InstancePodConfig with the expected k8s-shaped fields.
func TestLoadInstancePodFromEnv(t *testing.T) {
	t.Setenv("KUBERNETES_INSTANCE_POD", `{
		"labels": {"team": "x"},
		"annotations": {"a": "b"},
		"nodeSelector": {"pool": "mcp"},
		"tolerations": [{"key": "mcp", "operator": "Exists", "effect": "NoSchedule"}],
		"imagePullSecrets": ["regcred"],
		"priorityClassName": "high"
	}`)

	ip := loadKubernetesConfig().InstancePod

	if ip.Labels["team"] != "x" || ip.Annotations["a"] != "b" {
		t.Fatalf("labels/annotations not parsed: %+v", ip)
	}
	if ip.NodeSelector["pool"] != "mcp" {
		t.Fatalf("nodeSelector not parsed: %+v", ip.NodeSelector)
	}
	if len(ip.Tolerations) != 1 || ip.Tolerations[0].Key != "mcp" || string(ip.Tolerations[0].Effect) != "NoSchedule" {
		t.Fatalf("tolerations not parsed: %+v", ip.Tolerations)
	}
	if len(ip.ImagePullSecrets) != 1 || ip.ImagePullSecrets[0] != "regcred" {
		t.Fatalf("imagePullSecrets not parsed: %+v", ip.ImagePullSecrets)
	}
	if ip.PriorityClassName != "high" {
		t.Fatalf("priorityClassName = %q", ip.PriorityClassName)
	}
}

func TestLoadInstancePodInvalidJSONFailsClosed(t *testing.T) {
	t.Setenv("KUBERNETES_INSTANCE_POD", "{not valid json")
	defer func() {
		if recover() == nil {
			t.Fatal("invalid placement JSON did not fail configuration")
		}
	}()
	_ = loadKubernetesConfig()
}

func TestInvalidConfiguredDurationFailsClosed(t *testing.T) {
	t.Setenv("STARTUP_TIMEOUT", "eventually")
	defer func() {
		if recover() == nil {
			t.Fatal("invalid duration did not fail configuration")
		}
	}()
	_ = Load()
}

func TestLoadConnectorConfiguration(t *testing.T) {
	t.Setenv("MCP_CONNECTOR_DATA_PLANE_ID", "65f5a680-3e6c-4f4a-920a-f8e2b31d7d53")
	t.Setenv("MCP_CONNECTOR_PLATFORM_API_URL", "https://platform.example")
	t.Setenv("MCP_CONNECTOR_AUTH_TIMEOUT", "7s")

	cfg := Load()
	if cfg.Connector.DataPlaneID != "65f5a680-3e6c-4f4a-920a-f8e2b31d7d53" || cfg.Connector.PlatformAPIURL != "https://platform.example" || cfg.Connector.AuthTimeout.String() != "7s" {
		t.Fatalf("connector config = %#v", cfg.Connector)
	}
}

func TestSandboxCanBeExplicitlyDisabled(t *testing.T) {
	t.Setenv("SANDBOX_ENABLED", "false")

	cfg := Load()
	if cfg.SandboxEnabled {
		t.Fatal("SandboxEnabled = true, want false")
	}
}
