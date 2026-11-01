package backends

import (
	"context"
	"strings"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	"github.com/agentarea/mcp-manager/internal/config"
)

const crashInstanceID = "22222222-2222-2222-2222-222222222222"

func crashObjects(container corev1.ContainerStatus, secret map[string][]byte, shapePod ...func(*corev1.Pod)) []client.Object {
	labels := map[string]string{
		"app.kubernetes.io/name":       "mcp-server",
		"app.kubernetes.io/instance":   "inst",
		"app.kubernetes.io/managed-by": "mcp-manager",
	}
	meta := metav1.ObjectMeta{Name: "mcp-inst", Namespace: graphTestNamespace, Labels: labels}
	deploymentMeta := meta
	deploymentMeta.CreationTimestamp = metav1.NewTime(time.Now().Add(-time.Minute))
	deployment := &appsv1.Deployment{
		ObjectMeta: deploymentMeta,
		Spec: appsv1.DeploymentSpec{
			Replicas: int32Ptr(1),
			Selector: &metav1.LabelSelector{MatchLabels: map[string]string{
				"app.kubernetes.io/name":     "mcp-server",
				"app.kubernetes.io/instance": "inst",
			}},
			Template: corev1.PodTemplateSpec{ObjectMeta: metav1.ObjectMeta{
				Annotations: map[string]string{"agentarea.io/instance-id": crashInstanceID},
			}},
		},
		Status: appsv1.DeploymentStatus{Replicas: 1},
	}
	container.Name = "mcp-server"
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: "mcp-inst-abc", Namespace: graphTestNamespace, Labels: labels,
			CreationTimestamp: metav1.Now(),
		},
		Status: corev1.PodStatus{ContainerStatuses: []corev1.ContainerStatus{container}},
	}
	for _, shape := range shapePod {
		shape(pod)
	}
	return []client.Object{
		deployment,
		pod,
		&corev1.ConfigMap{ObjectMeta: meta, Data: map[string]string{"port": "8080"}},
		&corev1.Secret{ObjectMeta: meta, Data: secret},
		&corev1.Service{ObjectMeta: meta},
	}
}

func crashStatus(t *testing.T, container corev1.ContainerStatus, secret map[string][]byte, shapePod ...func(*corev1.Pod)) *InstanceStatus {
	t.Helper()
	kube := fake.NewClientBuilder().WithScheme(graphScheme(t)).WithObjects(crashObjects(container, secret, shapePod...)...).Build()
	status, err := graphBackend(t, kube).GetInstanceStatus(context.Background(), crashInstanceID)
	if err != nil {
		t.Fatalf("GetInstanceStatus() error = %v", err)
	}
	return status
}

// An MCP server whose process exits before it ever listens crash-loops for as
// long as the startup probe allows. Reporting that as "starting" held every
// caller for the whole startup timeout, so a crashed container is a failed one.
func TestContainerThatCrashedBeforeReadyIsFailed(t *testing.T) {
	for name, container := range map[string]corev1.ContainerStatus{
		"back-off": {
			RestartCount: 1,
			State:        corev1.ContainerState{Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"}},
			LastTerminationState: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
				ExitCode: 1, Message: "sh: 1: some-server: not found\n",
			}},
		},
		"just exited": {
			State: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
				ExitCode: 1, Message: "sh: 1: some-server: not found\n",
			}},
		},
	} {
		t.Run(name, func(t *testing.T) {
			status := crashStatus(t, container, nil)
			if status.Status != "failed" {
				t.Fatalf("status = %q, want failed", status.Status)
			}
			if status.Message != "sh: 1: some-server: not found" {
				t.Fatalf("message = %q, want the server's own output", status.Message)
			}
		})
	}
}

func TestContainerStillStartingIsNotFailed(t *testing.T) {
	status := crashStatus(t, corev1.ContainerStatus{
		State: corev1.ContainerState{Running: &corev1.ContainerStateRunning{}},
	}, nil)
	if status.Status != "starting" {
		t.Fatalf("status = %q, want starting", status.Status)
	}
	if status.Message != "" {
		t.Fatalf("message = %q, want none", status.Message)
	}
}

var crashLooping = corev1.ContainerStatus{
	RestartCount: 3,
	State:        corev1.ContainerState{Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"}},
	LastTerminationState: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
		ExitCode: 1, Message: "the previous workload's output",
	}},
}

// A re-created workload starts while its predecessor's pods are still going
// away under the same labels. Their crash is not the new start's.
func TestPodsOfAnEarlierWorkloadDoNotFailANewStart(t *testing.T) {
	for name, shape := range map[string]func(*corev1.Pod){
		"being deleted": func(pod *corev1.Pod) {
			now := metav1.Now()
			pod.DeletionTimestamp = &now
			pod.Finalizers = []string{"test/keep"}
		},
		"created before the deployment": func(pod *corev1.Pod) {
			pod.CreationTimestamp = metav1.NewTime(time.Now().Add(-time.Hour))
		},
	} {
		t.Run(name, func(t *testing.T) {
			status := crashStatus(t, crashLooping, nil, shape)
			if status.Status != "starting" {
				t.Fatalf("status = %q, want starting: an earlier workload's pod failed the new start", status.Status)
			}
		})
	}
}

// A container restarted once long ago keeps that termination for the pod's
// life. Once its current run passed the startup probe, a moment of failed
// readiness under load is not a crash, and the workload must not be torn down.
func TestAStartedContainerIsNotFailedForAnOldRestart(t *testing.T) {
	started := true
	status := crashStatus(t, corev1.ContainerStatus{
		RestartCount: 1,
		Started:      &started,
		State:        corev1.ContainerState{Running: &corev1.ContainerStateRunning{}},
		LastTerminationState: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
			ExitCode: 137, Message: "killed by liveness probe yesterday",
		}},
	}, nil)
	if status.Status != "starting" {
		t.Fatalf("status = %q, want starting: a started container was failed for an old restart", status.Status)
	}
}

// The output is the server's stderr, and a server may print the credentials it
// was started with. The values of the instance's own secret never leave.
func TestCrashOutputCarriesNoSecretValue(t *testing.T) {
	status := crashStatus(t, corev1.ContainerStatus{
		State: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
			ExitCode: 1, Message: "auth failed for token tok-0123456789abcdef",
		}},
	}, map[string][]byte{"API_TOKEN": []byte("tok-0123456789abcdef")})
	if strings.Contains(status.Message, "tok-0123456789abcdef") {
		t.Fatalf("message = %q leaks the secret value", status.Message)
	}
	if !strings.Contains(status.Message, "auth failed for token") {
		t.Fatalf("message = %q lost the rest of the output", status.Message)
	}
}

func TestDeploymentAsksForTheLogTailOnError(t *testing.T) {
	container := renderDeployment(t, config.IsolationStandard).Spec.Template.Spec.Containers[0]
	if container.TerminationMessagePolicy != corev1.TerminationMessageFallbackToLogsOnError {
		t.Fatalf("terminationMessagePolicy = %q, want FallbackToLogsOnError", container.TerminationMessagePolicy)
	}
}

// A multi-line secret such as a PEM key reaches the output a line at a time.
func TestCrashOutputCarriesNoLineOfAMultiLineSecret(t *testing.T) {
	status := crashStatus(t, corev1.ContainerStatus{
		State: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
			ExitCode: 1, Message: "bad key line: MIIEvQIBADANBgkqhkiG9w0BAQEFAASC",
		}},
	}, map[string][]byte{"KEY": []byte("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----\n")})
	if strings.Contains(status.Message, "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC") {
		t.Fatalf("message = %q leaks a line of the secret", status.Message)
	}
}
