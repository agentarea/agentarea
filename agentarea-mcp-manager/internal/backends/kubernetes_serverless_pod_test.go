package backends

import (
	"context"
	"log/slog"
	"os"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	"github.com/agentarea/mcp-manager/internal/config"
)

func serverlessBackend(t *testing.T, tier string) *KubernetesBackend {
	t.Helper()
	cfg := &config.Config{}
	cfg.Container.DefaultIsolationTier = tier
	return &KubernetesBackend{
		client:           fake.NewClientBuilder().WithScheme(graphScheme(t)).Build(),
		config:           cfg,
		k8sConfig:        &config.KubernetesConfig{Namespace: graphTestNamespace},
		logger:           slog.New(slog.NewTextHandler(os.Stdout, nil)),
		scratchSizeLimit: resource.MustParse("256Mi"),
	}
}

func renderDeployment(t *testing.T, tier string) *appsv1.Deployment {
	t.Helper()
	backend := serverlessBackend(t, tier)
	spec := &InstanceSpec{
		InstanceID: "11111111-1111-1111-1111-111111111111",
		Name:       "instance",
		Image:      "ghcr.io/vendor/mcp:1.0",
		Port:       8080,
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

// The prod blocker this replaced: the provider pinned every MCP pod to the
// untrusted tier, which asks for a syscall-interposing RuntimeClass. On a
// cluster without one the pod never schedules, so every instance was
// permanently unreachable regardless of its image.
func TestStandardTierSchedulesOnTheNodeDefaultRuntime(t *testing.T) {
	deployment := renderDeployment(t, config.IsolationStandard)
	if name := deployment.Spec.Template.Spec.RuntimeClassName; name != nil {
		t.Fatalf("RuntimeClassName = %q; the standard tier must not demand a runtime the cluster may not have", *name)
	}
	container := deployment.Spec.Template.Spec.Containers[0]
	drops := container.SecurityContext.Capabilities.Drop
	if len(drops) == 0 {
		t.Fatal("the standard tier dropped no capabilities; it is confinement, not a bypass")
	}
}

// The tier still has to mean something: asking for untrusted must still produce
// the stronger runtime, so the fix above is a change of default and not a
// removal of the capability.
func TestUntrustedTierStillDemandsItsRuntime(t *testing.T) {
	deployment := renderDeployment(t, config.IsolationUntrusted)
	name := deployment.Spec.Template.Spec.RuntimeClassName
	if name == nil || *name != config.UntrustedRuntime {
		t.Fatalf("RuntimeClassName = %v, want %q", name, config.UntrustedRuntime)
	}
}

// Scale-to-zero means a caller pays the start latency on an ordinary request,
// so dead time in the probe is dead time in every cold call.
func TestReadinessIsPolledImmediatelyAndOftenOnColdStart(t *testing.T) {
	container := renderDeployment(t, config.IsolationStandard).Spec.Template.Spec.Containers[0]
	if container.ReadinessProbe.InitialDelaySeconds != 0 {
		t.Fatalf("readiness InitialDelaySeconds = %d; a fixed delay is latency the fastest image cannot avoid",
			container.ReadinessProbe.InitialDelaySeconds)
	}
	if container.ReadinessProbe.PeriodSeconds != 1 {
		t.Fatalf("readiness PeriodSeconds = %d, want 1", container.ReadinessProbe.PeriodSeconds)
	}
	if container.StartupProbe == nil {
		t.Fatal("no startup probe: a slow image has no budget without re-introducing an initial delay")
	}
	if container.StartupProbe.FailureThreshold < 60 {
		t.Fatalf("startup FailureThreshold = %d; too small a budget kills slow images",
			container.StartupProbe.FailureThreshold)
	}
	if container.LivenessProbe.InitialDelaySeconds == 0 {
		t.Fatal("liveness lost its initial delay and can now kill a container that is still starting")
	}
}

// A reaped instance holds its name and quota for the whole grace period, and an
// MCP workload has nothing to flush on the way out.
func TestTerminationIsNotLeftAtTheThirtySecondDefault(t *testing.T) {
	spec := renderDeployment(t, config.IsolationStandard).Spec.Template.Spec
	grace := spec.TerminationGracePeriodSeconds
	if grace == nil {
		t.Fatal("TerminationGracePeriodSeconds unset; Kubernetes then waits its 30s default")
	}
	if *grace > 10 {
		t.Fatalf("TerminationGracePeriodSeconds = %d; too long for a workload holding no state", *grace)
	}
}

// Nothing survives a restart, so unbounded scratch buys the instance nothing
// and lets one image exhaust the ephemeral storage of every pod on the node.
func TestEveryScratchVolumeIsBounded(t *testing.T) {
	spec := renderDeployment(t, config.IsolationStandard).Spec.Template.Spec
	if len(spec.Volumes) == 0 {
		t.Fatal("no volumes rendered")
	}
	for _, volume := range spec.Volumes {
		if volume.EmptyDir == nil {
			continue
		}
		if volume.EmptyDir.SizeLimit == nil || volume.EmptyDir.SizeLimit.IsZero() {
			t.Fatalf("volume %q has an unbounded emptyDir", volume.Name)
		}
	}
}
