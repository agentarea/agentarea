package backends

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"time"

	"github.com/agentarea/mcp-manager/internal/usage"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

const usageSampleTimeout = 30 * time.Second
const usageSourceTimeout = 5 * time.Second
const usageOwnerLabel = "agentarea.io/dataplane-id"

// The metrics wire types intentionally contain no environment, commands or secrets.
// Reading the aggregated API through the existing client avoids node proxy privileges.
type podUsageMetrics struct {
	Metadata   metav1.ObjectMeta `json:"metadata"`
	Timestamp  metav1.Time       `json:"timestamp"`
	Window     metav1.Duration   `json:"window"`
	Containers []struct {
		Name  string              `json:"name"`
		Usage corev1.ResourceList `json:"usage"`
	} `json:"containers"`
}

func (k *KubernetesBackend) SampleUsage(ctx context.Context) ([]usage.Sample, error) {
	return k.sampleUsage(ctx, "", "")
}

// SampleUsageForOwner restricts collection at the runtime boundary, before stats
// are fetched. Data planes must not expose another agent's workloads.
func (k *KubernetesBackend) SampleUsageForOwner(ctx context.Context, agentID string) ([]usage.Sample, error) {
	if agentID == "" {
		return nil, fmt.Errorf("usage owner is required")
	}
	return k.sampleUsage(ctx, agentID, "")
}

func (k *KubernetesBackend) SampleResourceUsage(ctx context.Context, resourceID string) ([]usage.Sample, error) {
	if resourceID == "" {
		return nil, fmt.Errorf("usage resource is required")
	}
	return k.sampleUsage(ctx, "", resourceID)
}

func (k *KubernetesBackend) SampleResourceUsageForOwner(ctx context.Context, agentID, resourceID string) ([]usage.Sample, error) {
	if agentID == "" || resourceID == "" {
		return nil, fmt.Errorf("usage owner and resource are required")
	}
	return k.sampleUsage(ctx, agentID, resourceID)
}

func (k *KubernetesBackend) sampleUsage(ctx context.Context, agentID, resourceID string) ([]usage.Sample, error) {
	ctx, cancel := context.WithTimeout(ctx, usageSampleTimeout)
	defer cancel()
	if k.k8sConfig == nil || k.k8sConfig.Namespace == "" {
		return nil, fmt.Errorf("usage namespace is required")
	}
	labels := client.MatchingLabels{"app.kubernetes.io/managed-by": "mcp-manager"}
	if agentID != "" {
		labels[usageOwnerLabel] = agentID
	}
	if resourceID != "" {
		labels["app.kubernetes.io/component"] = "mcp-server"
	}
	var pods corev1.PodList
	if err := k.client.List(ctx, &pods, client.InNamespace(k.k8sConfig.Namespace), labels); err != nil {
		return nil, fmt.Errorf("listing usage pods: %w", err)
	}
	samples := make([]usage.Sample, 0, len(pods.Items))
	selected := make([]*corev1.Pod, 0, len(pods.Items))
	for i := range pods.Items {
		pod := &pods.Items[i]
		component := pod.Labels["app.kubernetes.io/component"]
		if component != "mcp-server" && component != "warm-pool" && component != "workflow-sandbox" && component != "stateful-agent" {
			continue
		}
		// Logical MCP identity is an annotation, so filter it before allocation
		// processing or any metrics request; owner and managed labels are server-side.
		if resourceID != "" && (component != "mcp-server" || pod.Annotations["agentarea.io/instance-id"] != resourceID || pod.Annotations["agentarea.io/workspace-id"] == "") {
			continue
		}
		s := usage.Sample{Provider: "kubernetes", ResourceKind: "platform_runtime", ResourceID: pod.Namespace + "/" + pod.Name, IncarnationID: string(pod.UID), State: string(pod.Status.Phase), ObservedAt: time.Now().UTC(), MeasurementStatus: "unavailable", MeasurementReason: "metrics_missing"}
		if pod.Status.StartTime != nil {
			started := pod.Status.StartTime.Time
			s.StartedAt = &started
		}
		if component == "mcp-server" && pod.Annotations["agentarea.io/workspace-id"] != "" {
			s.ResourceKind = "mcp_instance"
			s.WorkspaceID = pod.Annotations["agentarea.io/workspace-id"]
			if id := pod.Annotations["agentarea.io/instance-id"]; id != "" {
				s.ResourceID = id
			}
		} else if (component == "workflow-sandbox" || component == "warm-pool") && pod.Annotations["mcp.agentarea.io/workspace-id"] != "" && pod.Annotations["mcp.agentarea.io/task-id"] != "" {
			s.ResourceKind = "sandbox"
			s.WorkspaceID = pod.Annotations["mcp.agentarea.io/workspace-id"]
			s.TaskID = pod.Annotations["mcp.agentarea.io/task-id"]
		}
		requests, limits := podUsageResources(pod)
		var err error
		if s.CPURequestNanocores, err = usageQuantity(requests, corev1.ResourceCPU, resource.Nano); err != nil {
			return nil, err
		}
		if s.CPULimitNanocores, err = usageQuantity(limits, corev1.ResourceCPU, resource.Nano); err != nil {
			return nil, err
		}
		if s.MemoryRequestBytes, err = usageQuantity(requests, corev1.ResourceMemory, 0); err != nil {
			return nil, err
		}
		if s.MemoryLimitBytes, err = usageQuantity(limits, corev1.ResourceMemory, 0); err != nil {
			return nil, err
		}
		samples = append(samples, s)
		selected = append(selected, pod)
	}
	if len(samples) == 0 {
		return samples, nil
	}
	k.applyUsageMetrics(ctx, agentID, resourceID, samples, selected)
	return samples, nil
}

func (k *KubernetesBackend) applyUsageMetrics(ctx context.Context, agentID, resourceID string, samples []usage.Sample, selected []*corev1.Pod) {
	metricsCtx, metricsCancel := context.WithTimeout(ctx, usageSourceTimeout)
	defer metricsCancel()
	if resourceID != "" {
		for i, pod := range selected {
			if k.clientset == nil || k.clientset.CoreV1().RESTClient() == nil {
				samples[i].MeasurementReason = "metrics_api_unavailable"
				continue
			}
			body, err := k.clientset.CoreV1().RESTClient().Get().AbsPath("/apis/metrics.k8s.io/v1beta1/namespaces/"+pod.Namespace+"/pods/"+pod.Name).SetHeader("Accept", "application/json").DoRaw(metricsCtx)
			var metric podUsageMetrics
			if err != nil || json.Unmarshal(body, &metric) != nil {
				samples[i].MeasurementReason = "metrics_api_unavailable"
				continue
			}
			if metric.Metadata.Name != pod.Name || metric.Metadata.Namespace != pod.Namespace {
				samples[i].MeasurementReason = "metrics_identity_or_window_invalid"
				continue
			}
			applyPodUsageMetrics(&samples[i], pod, &metric)
		}
		return
	}
	var payload struct {
		Items []podUsageMetrics `json:"items"`
	}
	var metricsErr error
	if k.clientset == nil || k.clientset.CoreV1().RESTClient() == nil {
		metricsErr = fmt.Errorf("metrics client unavailable")
	} else {
		request := k.clientset.CoreV1().RESTClient().Get().AbsPath("/apis/metrics.k8s.io/v1beta1/namespaces/"+k.k8sConfig.Namespace+"/pods").SetHeader("Accept", "application/json")
		if agentID != "" {
			request.Param("labelSelector", usageOwnerLabel+"="+agentID)
		}
		body, err := request.DoRaw(metricsCtx)
		metricsErr = err
		if metricsErr == nil {
			metricsErr = json.Unmarshal(body, &payload)
		}
	}
	if metricsErr != nil {
		for i := range samples {
			samples[i].MeasurementReason = "metrics_api_unavailable"
		}
		return
	}
	byName := make(map[string]*podUsageMetrics, len(payload.Items))
	for i := range payload.Items {
		metric := &payload.Items[i]
		if metric.Metadata.Namespace == k.k8sConfig.Namespace {
			byName[metric.Metadata.Name] = metric
		}
	}
	for i := range samples {
		if metric := byName[selected[i].Name]; metric != nil {
			applyPodUsageMetrics(&samples[i], selected[i], metric)
		}
	}
}

func applyPodUsageMetrics(s *usage.Sample, pod *corev1.Pod, metric *podUsageMetrics) {
	// Metrics servers may omit UID. A window predating this pod cannot be
	// attributed to it when a pod name was reused.
	windowStart := metric.Timestamp.Add(-metric.Window.Duration)
	if metric.Timestamp.IsZero() || metric.Window.Duration <= 0 || (metric.Metadata.UID != "" && metric.Metadata.UID != pod.UID) || (s.StartedAt != nil && windowStart.Before(*s.StartedAt)) {
		s.MeasurementReason = "metrics_identity_or_window_invalid"
		return
	}
	if pod.Status.Phase != corev1.PodRunning {
		s.MeasurementReason = "pod_not_running"
		return
	}
	expected := make(map[string]bool, len(pod.Spec.Containers)+len(pod.Spec.InitContainers))
	for _, container := range pod.Spec.Containers {
		expected[container.Name] = true
	}
	for _, container := range pod.Spec.InitContainers {
		if container.RestartPolicy != nil && *container.RestartPolicy == corev1.ContainerRestartPolicyAlways {
			expected[container.Name] = true
		}
	}
	// Include any currently running init or ephemeral container; a partial pod
	// sum must never be presented as its total measurement.
	for _, statuses := range [][]corev1.ContainerStatus{pod.Status.InitContainerStatuses, pod.Status.EphemeralContainerStatuses} {
		for _, status := range statuses {
			if status.State.Running != nil {
				expected[status.Name] = true
			}
		}
	}
	seen := make(map[string]bool, len(metric.Containers))
	var cpu, memory int64
	for _, container := range metric.Containers {
		if seen[container.Name] {
			s.MeasurementReason = "metrics_incomplete"
			return
		}
		seen[container.Name] = true
		c, cpuErr := usageQuantity(container.Usage, corev1.ResourceCPU, resource.Nano)
		m, memoryErr := usageQuantity(container.Usage, corev1.ResourceMemory, 0)
		if cpuErr != nil || memoryErr != nil || c == nil || m == nil || *c > math.MaxInt64-cpu || *m > math.MaxInt64-memory {
			s.MeasurementReason = "metrics_incomplete"
			return
		}
		cpu += *c
		memory += *m
	}
	for name := range expected {
		if !seen[name] {
			s.MeasurementReason = "metrics_incomplete"
			return
		}
	}
	if len(seen) == 0 {
		s.MeasurementReason = "metrics_incomplete"
		return
	}
	memoryBytes := uint64(memory)
	window := int64(metric.Window.Duration)
	measured := metric.Timestamp.Time
	s.MeasurementAt = &measured
	s.CPUUsageNanocores, s.CPUWindowNS, s.MemoryUsageBytes = &cpu, &window, &memoryBytes
	s.MemoryMetric = "working_set"
	s.MeasurementStatus, s.MeasurementReason = "available", ""
}

func usageQuantity(resources corev1.ResourceList, name corev1.ResourceName, scale resource.Scale) (*int64, error) {
	q, ok := resources[name]
	if !ok {
		return nil, nil
	}
	maximum := resource.NewScaledQuantity(math.MaxInt64, scale)
	if q.Sign() < 0 || q.Cmp(*maximum) > 0 {
		return nil, fmt.Errorf("usage %s quantity exceeds nonnegative int64 units", name)
	}
	value := q.ScaledValue(scale)
	return &value, nil
}

// Match Kubernetes scheduling accounting: sum application containers and
// restartable init containers, take the peak sequential init phase, then apply
// pod-level budgets and overhead. Keep requests and limits separate.
func podUsageResources(pod *corev1.Pod) (corev1.ResourceList, corev1.ResourceList) {
	calculate := func(limits bool) corev1.ResourceList {
		resources := func(r corev1.ResourceRequirements) corev1.ResourceList {
			if limits {
				return r.Limits
			}
			return r.Requests
		}
		total, sidecars, peak := corev1.ResourceList{}, corev1.ResourceList{}, corev1.ResourceList{}
		for _, c := range pod.Spec.Containers {
			addUsageResources(total, resources(c.Resources))
		}
		for _, c := range pod.Spec.InitContainers {
			current := resources(c.Resources)
			if c.RestartPolicy != nil && *c.RestartPolicy == corev1.ContainerRestartPolicyAlways {
				addUsageResources(total, current)
				addUsageResources(sidecars, current)
				current = sidecars
			} else {
				current = current.DeepCopy()
				if current == nil {
					current = corev1.ResourceList{}
				}
				addUsageResources(current, sidecars)
			}
			maxUsageResources(peak, current)
		}
		maxUsageResources(total, peak)
		if pod.Spec.Resources != nil {
			for name, value := range resources(*pod.Spec.Resources) {
				if name == corev1.ResourceCPU || name == corev1.ResourceMemory {
					total[name] = value.DeepCopy()
				}
			}
		}
		for name, overhead := range pod.Spec.Overhead {
			value, exists := total[name]
			if limits && (!exists || value.IsZero()) {
				continue
			}
			value.Add(overhead)
			total[name] = value
		}
		return total
	}
	return calculate(false), calculate(true)
}

func addUsageResources(target, source corev1.ResourceList) {
	for name, value := range source {
		if name != corev1.ResourceCPU && name != corev1.ResourceMemory {
			continue
		}
		current := target[name]
		current.Add(value)
		target[name] = current
	}
}

func maxUsageResources(target, source corev1.ResourceList) {
	for name, value := range source {
		if name != corev1.ResourceCPU && name != corev1.ResourceMemory {
			continue
		}
		current, exists := target[name]
		if !exists || value.Cmp(current) > 0 {
			target[name] = value.DeepCopy()
		}
	}
}
