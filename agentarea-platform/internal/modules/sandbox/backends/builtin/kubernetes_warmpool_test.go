package builtin

import (
	"context"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/warmpool"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

func TestExecuteSandboxRequiresTaskIdentity(t *testing.T) {
	backend := &Kubernetes{}
	_, err := backend.ExecuteSandbox(context.Background(), warmpool.ExecuteRequest{
		WorkflowID: "workflow-owner",
	})
	if err == nil || !strings.Contains(err.Error(), "task_id is required") {
		t.Fatalf("ExecuteSandbox() error = %v, want task_id requirement", err)
	}
}

func TestRuntimeManifestFailsWithoutReadyRuntime(t *testing.T) {
	clientset := fake.NewSimpleClientset(&corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "sandbox-runtime",
			Namespace: "agentarea",
			Labels: map[string]string{
				"app.kubernetes.io/component": "warm-pool",
				"mcp.agentarea.io/status":     "waiting",
			},
		},
	})
	backend := &Kubernetes{
		clientset: clientset,
		namespace: "agentarea",
	}

	_, err := backend.RuntimeManifest(context.Background())
	if err == nil || !strings.Contains(err.Error(), "no ready runtime pods") {
		t.Fatalf("RuntimeManifest() error = %v, want no ready runtime pods", err)
	}
}
