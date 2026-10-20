package backends

import (
	"context"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/types"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

func deploymentWithLabels(t *testing.T, operatorLabels, specLabels map[string]string) *appsv1.Deployment {
	t.Helper()
	backend := serverlessBackend(t, config.IsolationStandard)
	backend.k8sConfig.InstancePod.Labels = operatorLabels
	spec := &InstanceSpec{
		InstanceID: "11111111-1111-1111-1111-111111111111",
		Name:       "instance",
		Image:      "ghcr.io/vendor/mcp:1.0",
		Port:       8080,
		Labels:     specLabels,
	}
	if err := backend.createDeployment(context.Background(), "instance", spec); err != nil {
		t.Fatal(err)
	}
	deployment := &appsv1.Deployment{}
	key := types.NamespacedName{Namespace: graphTestNamespace, Name: "mcp-instance"}
	if err := backend.client.Get(context.Background(), key, deployment); err != nil {
		t.Fatal(err)
	}
	return deployment
}

// The egress label moves a pod out of the default egress policy, so the pod gets
// it from the spec the platform assembled and from nowhere else.
func TestDeploymentCarriesTheSpecEgressLabelOnly(t *testing.T) {
	podLabels := deploymentWithLabels(t,
		map[string]string{models.EgressLabel: "from-operator"},
		map[string]string{models.EgressLabel: "exit-a", "team": "a"},
	).Spec.Template.Labels

	if podLabels[models.EgressLabel] != "exit-a" {
		t.Fatalf("pod egress label = %q, want exit-a", podLabels[models.EgressLabel])
	}
	if _, ok := podLabels["team"]; ok {
		t.Fatalf("an arbitrary spec label reached the pod: %v", podLabels)
	}
}

func TestOperatorPodLabelsCannotSetTheEgressLabel(t *testing.T) {
	podLabels := deploymentWithLabels(t, map[string]string{models.EgressLabel: "from-operator"}, nil).Spec.Template.Labels

	if value, ok := podLabels[models.EgressLabel]; ok {
		t.Fatalf("pod egress label = %q from operator defaults", value)
	}
}
