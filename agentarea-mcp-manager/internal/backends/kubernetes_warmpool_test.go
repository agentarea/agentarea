package backends

import (
	"context"
	"strings"
	"testing"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

func TestExecuteSandboxRequiresTaskIdentity(t *testing.T) {
	backend := &KubernetesBackend{}
	_, err := backend.ExecuteSandbox(context.Background(), warmpool.ExecuteRequest{
		WorkflowID: "legacy-workflow-owner",
	})
	if err == nil || !strings.Contains(err.Error(), "task_id is required") {
		t.Fatalf("ExecuteSandbox() error = %v, want task_id requirement", err)
	}
}

func TestRuntimeManifestSelectsExactPackageInstallProfile(t *testing.T) {
	clientset := fake.NewSimpleClientset(&corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "allowed-runtime",
			Namespace: "agentarea",
			Labels: map[string]string{
				"app.kubernetes.io/component":      "warm-pool",
				"mcp.agentarea.io/status":          "waiting",
				"mcp.agentarea.io/package-install": "allowed",
			},
		},
	})
	backend := &KubernetesBackend{
		clientset: clientset,
		k8sConfig: &config.KubernetesConfig{Namespace: "agentarea"},
	}

	_, err := backend.RuntimeManifest(context.Background(), "locked")
	if err == nil || !strings.Contains(err.Error(), `profile "locked"`) {
		t.Fatalf("RuntimeManifest() error = %v, want exact locked-profile selection failure", err)
	}
}
