package backends

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/usage"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

func usageTestPod() *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: "mcp-one", Namespace: "runtime", UID: "pod-one", Labels: map[string]string{"app.kubernetes.io/managed-by": "mcp-manager", "app.kubernetes.io/component": "mcp-server"}, Annotations: map[string]string{"agentarea.io/workspace-id": "workspace-one", "agentarea.io/instance-id": "instance-one"}},
		Spec:       corev1.PodSpec{Containers: []corev1.Container{{Name: "server", Resources: corev1.ResourceRequirements{Requests: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("125m"), corev1.ResourceMemory: resource.MustParse("32Mi")}, Limits: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("1"), corev1.ResourceMemory: resource.MustParse("64Mi")}}}}},
		Status:     corev1.PodStatus{Phase: corev1.PodRunning, StartTime: &metav1.Time{Time: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)}},
	}
}

func usageTestBackend(t *testing.T, pod *corev1.Pod, metrics http.HandlerFunc) *KubernetesBackend {
	t.Helper()
	server := httptest.NewServer(metrics)
	t.Cleanup(server.Close)
	clientset, err := kubernetes.NewForConfig(&rest.Config{Host: server.URL})
	if err != nil {
		t.Fatal(err)
	}
	scheme := runtime.NewScheme()
	if err := corev1.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	return &KubernetesBackend{client: fake.NewClientBuilder().WithScheme(scheme).WithObjects(pod).Build(), clientset: clientset, k8sConfig: &config.KubernetesConfig{Namespace: "runtime"}}
}

func TestUsageMissingMetricsRetainsAllocation(t *testing.T) {
	backend := usageTestBackend(t, usageTestPod(), func(w http.ResponseWriter, r *http.Request) { http.NotFound(w, r) })
	samples, err := backend.SampleUsage(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) != 1 {
		t.Fatalf("samples = %v", samples)
	}
	s := samples[0]
	if s.MeasurementStatus != "unavailable" || s.CPUUsageNanocores != nil || s.MemoryUsageBytes != nil {
		t.Fatalf("missing metrics fabricated usage: %+v", s)
	}
	if s.CPURequestNanocores == nil || *s.CPURequestNanocores != 125000000 || s.MemoryLimitBytes == nil || *s.MemoryLimitBytes != 64<<20 {
		t.Fatalf("allocation lost: %+v", s)
	}
	if s.WorkspaceID != "workspace-one" || s.IncarnationID != "pod-one" {
		t.Fatalf("ownership lost: %+v", s)
	}
}

func TestUsageMetricsPreserveNanocoresAndWindow(t *testing.T) {
	backend := usageTestBackend(t, usageTestPod(), func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/apis/metrics.k8s.io/v1beta1/namespaces/runtime/pods" {
			t.Errorf("unexpected metrics path %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"items":[{"metadata":{"name":"mcp-one","namespace":"runtime"},"timestamp":"2026-01-01T00:00:30Z","window":"15s","containers":[{"name":"server","usage":{"cpu":"123456789n","memory":"9007199254740993"}}]}]}`))
	})
	samples, err := backend.SampleUsage(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	s := samples[0]
	if s.MeasurementStatus != "available" || s.CPUUsageNS != nil || s.CPUUsageNanocores == nil || *s.CPUUsageNanocores != 123456789 || s.CPUWindowNS == nil || *s.CPUWindowNS != int64(15*time.Second) || s.MemoryUsageBytes == nil || *s.MemoryUsageBytes != 9007199254740993 || s.MemoryMetric != "working_set" {
		t.Fatalf("lossy metrics: %+v", s)
	}
}

func TestUsageRejectsMetricsFromPreviousPodIncarnation(t *testing.T) {
	pod := usageTestPod()
	backend := usageTestBackend(t, pod, func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"items": []any{map[string]any{"metadata": map[string]string{"name": pod.Name, "namespace": pod.Namespace}, "timestamp": "2025-12-31T23:59:59Z", "window": "15s", "containers": []any{map[string]any{"name": "server", "usage": map[string]string{"cpu": "1", "memory": "1Mi"}}}}}})
	})
	samples, err := backend.SampleUsage(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if samples[0].MeasurementStatus != "unavailable" || samples[0].CPUUsageNanocores != nil {
		t.Fatalf("attributed stale metrics: %+v", samples[0])
	}
}

func TestUsagePodResourcesIncludeInitSidecarsAndOverhead(t *testing.T) {
	pod := usageTestPod()
	always := corev1.ContainerRestartPolicyAlways
	pod.Spec.InitContainers = []corev1.Container{
		{Name: "sidecar", RestartPolicy: &always, Resources: corev1.ResourceRequirements{Requests: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("25m")}}},
		{Name: "setup", Resources: corev1.ResourceRequirements{Requests: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("500m")}}},
	}
	pod.Spec.Overhead = corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("10m")}
	requests, _ := podUsageResources(pod)
	cpu := requests[corev1.ResourceCPU]
	if cpu.ScaledValue(resource.Nano) != 535000000 {
		t.Fatalf("effective CPU = %s", cpu.String())
	}
	pod.Spec.Resources = &corev1.ResourceRequirements{Requests: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("750m")}}
	requests, _ = podUsageResources(pod)
	cpu = requests[corev1.ResourceCPU]
	if cpu.ScaledValue(resource.Nano) != 760000000 {
		t.Fatalf("pod budget did not override container sum: %s", cpu.String())
	}
}

func TestUsageUnassignedPoolIsNotTenantUsage(t *testing.T) {
	pod := usageTestPod()
	pod.Labels["app.kubernetes.io/component"] = "warm-pool"
	pod.Annotations = nil
	backend := usageTestBackend(t, pod, func(w http.ResponseWriter, r *http.Request) { http.NotFound(w, r) })
	samples, err := backend.SampleUsage(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if samples[0].ResourceKind != "platform_runtime" || samples[0].WorkspaceID != "" || samples[0].TaskID != "" {
		t.Fatalf("pool attributed to tenant: %+v", samples[0])
	}
}

func TestUsageOwnerScopeFiltersBeforeMetricsCall(t *testing.T) {
	pod := usageTestPod()
	pod.Labels[usageOwnerLabel] = "other-agent"
	backend := usageTestBackend(t, pod, func(w http.ResponseWriter, r *http.Request) {
		t.Error("unowned pod triggered a metrics request")
		http.NotFound(w, r)
	})
	samples, err := backend.SampleUsageForOwner(context.Background(), "agent-one")
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) != 0 {
		t.Fatalf("unowned pod leaked: %+v", samples)
	}
}

func TestUsageResourceTargetingAndOwnerConjunction(t *testing.T) {
	target := usageTestPod()
	target.Labels[usageOwnerLabel] = "agent-one"
	backend := usageTestBackend(t, target, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/apis/metrics.k8s.io/v1beta1/namespaces/runtime/pods/mcp-one" {
			t.Errorf("targeted sampling fetched unrelated metrics: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"metadata":{"name":"mcp-one","namespace":"runtime"},"timestamp":"2026-01-01T00:00:30.123456789Z","window":"15s","containers":[{"name":"server","usage":{"cpu":"123456789n","memory":"9007199254740993"}}]}`))
	})
	for _, tc := range []struct{ name, owner, id, component, managed string }{
		{"other-resource", "agent-one", "instance-two", "mcp-server", "mcp-manager"},
		{"other-owner", "other-agent", "instance-one", "mcp-server", "mcp-manager"},
		{"other-component", "agent-one", "instance-one", "warm-pool", "mcp-manager"},
		{"unmanaged", "agent-one", "instance-one", "mcp-server", "other-manager"},
	} {
		pod := target.DeepCopy()
		pod.Name, pod.ResourceVersion = tc.name, ""
		pod.Labels[usageOwnerLabel] = tc.owner
		pod.Labels["app.kubernetes.io/component"] = tc.component
		pod.Labels["app.kubernetes.io/managed-by"] = tc.managed
		pod.Annotations["agentarea.io/instance-id"] = tc.id
		if err := backend.client.Create(context.Background(), pod); err != nil {
			t.Fatal(err)
		}
	}
	samples, err := backend.SampleResourceUsageForOwner(context.Background(), "agent-one", "instance-one")
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) != 1 || samples[0].IncarnationID != "pod-one" || samples[0].CPUUsageNanocores == nil || *samples[0].CPUUsageNanocores != 123456789 {
		t.Fatalf("targeted sample = %+v", samples)
	}
	if samples[0].MeasurementAt == nil || samples[0].MeasurementAt.Nanosecond() != 123456789 {
		t.Fatalf("timestamp lost: %+v", samples[0])
	}
	if err := backend.client.Delete(context.Background(), target); err != nil {
		t.Fatal(err)
	}
	samples, err = backend.SampleResourceUsageForOwner(context.Background(), "agent-one", "instance-one")
	if err != nil || samples == nil || len(samples) != 0 {
		t.Fatalf("deleted resource leaked other inventory: samples=%v err=%v", samples, err)
	}
}

func TestUsageResourceSamplingRetainsUnavailableAllocation(t *testing.T) {
	backend := usageTestBackend(t, usageTestPod(), func(w http.ResponseWriter, r *http.Request) { http.NotFound(w, r) })
	var sampler usage.ResourceSampler = backend
	samples, err := sampler.SampleResourceUsage(context.Background(), "instance-one")
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) != 1 || samples[0].MeasurementStatus != "unavailable" || samples[0].MemoryLimitBytes == nil || *samples[0].MemoryLimitBytes != 64<<20 {
		t.Fatalf("target allocation lost: %+v", samples)
	}
	if err := backend.client.DeleteAllOf(context.Background(), &corev1.Pod{}, client.InNamespace("runtime")); err != nil {
		t.Fatal(err)
	}
	samples, err = sampler.SampleResourceUsage(context.Background(), "instance-one")
	if err != nil || samples == nil || len(samples) != 0 {
		t.Fatalf("empty inventory: samples=%v err=%v", samples, err)
	}
}
