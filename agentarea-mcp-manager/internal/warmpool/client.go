package warmpool

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

const (
	labelComponent  = "app.kubernetes.io/component"
	labelManagedBy  = "app.kubernetes.io/managed-by"
	labelStatus     = "mcp.agentarea.io/status"
	labelWorkflowID = "mcp.agentarea.io/workflow-id"

	statusWaiting  = "waiting"
	statusAssigned = "assigned"
	statusIdle     = "idle"

	annotationWorkflowAssignedAt = "mcp.agentarea.io/workflow-assigned-at"
	annotationWorkflowLastUsedAt = "mcp.agentarea.io/workflow-last-used-at"
	annotationWorkflowLeaseUntil = "mcp.agentarea.io/workflow-lease-until"
	annotationWorkflowIdleSince  = "mcp.agentarea.io/workflow-idle-since"
	annotationWorkflowCleanupAt  = "mcp.agentarea.io/workflow-cleanup-at"
)

// Client manages warm pool operations
type Client struct {
	client    kubernetes.Interface
	namespace string
	timeout   time.Duration
}

// Config holds warm pool configuration
type Config struct {
	Enabled     bool
	Size        int
	Namespace   string
	Timeout     time.Duration
	RunnerImage string
}

// DefaultConfig returns default configuration
func DefaultConfig() Config {
	return Config{
		Enabled:     true,
		Size:        10,
		Namespace:   "mcp-system",
		Timeout:     30 * time.Second,
		RunnerImage: "agentarea/mcp-runner:latest",
	}
}

// NewClient creates a new warm pool client
func NewClient(client kubernetes.Interface, namespace string) *Client {
	return &Client{
		client:    client,
		namespace: namespace,
		timeout:   120 * time.Second,
	}
}

// FindAvailablePod finds a warm pod in "waiting" state
func (c *Client) FindAvailablePod(ctx context.Context) (*corev1.Pod, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf("%s=warm-pool,%s=%s", labelComponent, labelStatus, statusWaiting),
		Limit:         1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list warm pods: %w", err)
	}

	if len(pods.Items) == 0 {
		return nil, fmt.Errorf("no warm pods available")
	}

	return &pods.Items[0], nil
}

// AssignPod marks a pod as assigned to a specific MCP instance
func (c *Client) AssignPod(ctx context.Context, pod *corev1.Pod, instance *models.MCPServerInstance) (*corev1.Pod, error) {
	if pod.Labels == nil {
		pod.Labels = make(map[string]string)
	}

	pod.Labels["mcp.agentarea.io/status"] = "activating"
	pod.Labels["mcp.agentarea.io/instance-id"] = instance.InstanceID
	pod.Labels["mcp.agentarea.io/instance-name"] = instance.Name

	updated, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to assign pod: %w", err)
	}

	return updated, nil
}

// ActivationRequest holds activation parameters
type ActivationRequest struct {
	MCPImage     string            `json:"mcp_image"`
	MCPImageHash string            `json:"mcp_image_hash"`
	Port         int               `json:"port"`
	Entrypoint   []string          `json:"entrypoint,omitempty"`
	Command      []string          `json:"command,omitempty"`
	Env          map[string]string `json:"env,omitempty"`
	HealthCheck  *HealthCheck      `json:"health_check,omitempty"`
}

// HealthCheck represents health check configuration
type HealthCheck struct {
	Path string `json:"path,omitempty"`
	Port int    `json:"port,omitempty"`
}

// ActivationResponse holds activation result
type ActivationResponse struct {
	Status           string `json:"status"`
	MCPPort          int    `json:"mcp_port"`
	ActivationTimeMs int    `json:"activation_time_ms"`
}

// ActivatePod triggers activation inside the pod
func (c *Client) ActivatePod(ctx context.Context, pod *corev1.Pod, req ActivationRequest) error {
	podIP := pod.Status.PodIP
	if podIP == "" {
		return fmt.Errorf("pod has no IP address")
	}

	url := fmt.Sprintf("http://%s:8080/activate", podIP)

	body, err := json.Marshal(req)
	if err != nil {
		return fmt.Errorf("failed to marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: c.timeout}
	resp, err := client.Do(httpReq)
	if err != nil {
		return fmt.Errorf("activation request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("activation returned status %d", resp.StatusCode)
	}

	var result ActivationResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return fmt.Errorf("failed to decode response: %w", err)
	}

	if result.Status != "ready" {
		return fmt.Errorf("activation failed: status=%s", result.Status)
	}

	return nil
}

// ExecuteRequest holds script execution parameters.
//
// WorkflowID, when set, opts the call into per-workflow workspace
// persistence: the activation service routes the script to
// /workspace/wf-<id>/ and keeps it across calls. Cleanup is the caller's
// responsibility — invoke DELETE /sandbox/workflow/:id when the workflow
// completes.
type ExecuteRequest struct {
	ScriptContent  string             `json:"script_content"`
	ScriptName     string             `json:"script_name"`
	Args           []string           `json:"args,omitempty"`
	Env            map[string]string  `json:"env,omitempty"`
	InputFiles     []SandboxInputFile `json:"input_files,omitempty"`
	ArtifactPaths  []string           `json:"artifact_paths,omitempty"`
	TimeoutSeconds int                `json:"timeout_seconds,omitempty"`
	WorkflowID     string             `json:"workflow_id,omitempty"`
}

// SandboxInputFile is a caller-provided file to materialize inside the sandbox workspace.
type SandboxInputFile struct {
	Path          string `json:"path"`
	ContentBase64 string `json:"content_base64"`
	ContentType   string `json:"content_type,omitempty"`
}

// SandboxArtifact is a file produced by a sandbox command and requested by the caller.
type SandboxArtifact struct {
	Path          string `json:"path"`
	Name          string `json:"name,omitempty"`
	ContentType   string `json:"content_type,omitempty"`
	Size          int64  `json:"size,omitempty"`
	ContentBase64 string `json:"content_base64,omitempty"`
	Error         string `json:"error,omitempty"`
}

// ExecuteResponse holds script execution result
type ExecuteResponse struct {
	Stdout          string            `json:"stdout"`
	Stderr          string            `json:"stderr"`
	ExitCode        int               `json:"exit_code"`
	ExecutionTimeMs int64             `json:"execution_time_ms"`
	Artifacts       []SandboxArtifact `json:"artifacts,omitempty"`
}

// ExecuteInPod sends a script execution request to a warm pod.
// The pod stays in "waiting" state — no assignment needed for stateless execution.
func (c *Client) ExecuteInPod(ctx context.Context, pod *corev1.Pod, req ExecuteRequest) (*ExecuteResponse, error) {
	podIP := pod.Status.PodIP
	if podIP == "" {
		return nil, fmt.Errorf("pod has no IP address")
	}
	return PostExecute(ctx, fmt.Sprintf("http://%s:8080/execute", podIP), req, c.timeout)
}

// PostExecute sends an ExecuteRequest to a sandbox executor's /execute endpoint
// and returns the parsed result. The endpoint is the same whether it is a
// Kubernetes warm pod (warm-pool data plane) or the dev/compose sandbox-executor
// container, so both backends share this transport.
func PostExecute(ctx context.Context, executeURL string, req ExecuteRequest, baseTimeout time.Duration) (*ExecuteResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	timeout := baseTimeout
	if req.TimeoutSeconds > 0 {
		// Add buffer for network overhead
		timeout = time.Duration(req.TimeoutSeconds+5) * time.Second
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", executeURL, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: timeout}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("execute request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("execute returned status %d", resp.StatusCode)
	}

	var result ExecuteResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &result, nil
}

// MarkReady marks pod as ready for traffic
func (c *Client) MarkReady(ctx context.Context, pod *corev1.Pod) (*corev1.Pod, error) {
	if pod.Labels == nil {
		pod.Labels = make(map[string]string)
	}

	pod.Labels["mcp.agentarea.io/status"] = "ready"

	updated, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to mark pod ready: %w", err)
	}

	return updated, nil
}

// ReturnToPool returns a pod to the waiting pool
func (c *Client) ReturnToPool(ctx context.Context, pod *corev1.Pod) error {
	// Remove assignment labels
	delete(pod.Labels, "mcp.agentarea.io/status")
	delete(pod.Labels, "mcp.agentarea.io/instance-id")
	delete(pod.Labels, "mcp.agentarea.io/instance-name")

	// Mark as waiting
	pod.Labels["mcp.agentarea.io/status"] = "waiting"

	_, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
	return err
}

// FindOrAssignPodForWorkflow returns the pod assigned to a given workflow id,
// allocating one if needed. Pod stickiness is what gives the per-workflow
// sandbox its state — every call routed through the same pod hits the same
// /workspace/wf-<id>/ directory. If the regular warm pool is exhausted, a
// workflow-scoped pod is cloned from a warm-pool template instead of falling
// back to a stateless executor.
func (c *Client) FindOrAssignPodForWorkflow(ctx context.Context, workflowID string) (*corev1.Pod, error) {
	now := time.Now().UTC()
	selector := fmt.Sprintf("%s=%s", labelWorkflowID, workflowID)
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: selector,
		Limit:         1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list pods for workflow %s: %w", workflowID, err)
	}
	if len(pods.Items) > 0 {
		pod := &pods.Items[0]
		if pod.Labels[labelStatus] == statusIdle {
			return c.markWorkflowAssigned(ctx, pod, workflowID, now, defaultWorkflowLeaseTTL())
		}
		return pod, nil
	}

	pod, err := c.FindAvailablePod(ctx)
	if err != nil {
		return c.createWorkflowPodFromTemplate(ctx, workflowID, now, defaultWorkflowLeaseTTL())
	}
	return c.markWorkflowAssigned(ctx, pod, workflowID, now, defaultWorkflowLeaseTTL())
}

func (c *Client) markWorkflowAssigned(ctx context.Context, pod *corev1.Pod, workflowID string, now time.Time, leaseTTL time.Duration) (*corev1.Pod, error) {
	if pod.Labels == nil {
		pod.Labels = make(map[string]string)
	}
	if pod.Annotations == nil {
		pod.Annotations = make(map[string]string)
	}
	if _, ok := pod.Annotations[annotationWorkflowAssignedAt]; !ok {
		pod.Annotations[annotationWorkflowAssignedAt] = now.Format(time.RFC3339)
	}
	pod.Labels[labelWorkflowID] = workflowID
	pod.Labels[labelStatus] = statusAssigned
	pod.Annotations[annotationWorkflowLastUsedAt] = now.Format(time.RFC3339)
	pod.Annotations[annotationWorkflowLeaseUntil] = now.Add(leaseTTL).Format(time.RFC3339)
	delete(pod.Annotations, annotationWorkflowIdleSince)
	delete(pod.Annotations, annotationWorkflowCleanupAt)

	updated, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to assign pod to workflow %s: %w", workflowID, err)
	}
	return updated, nil
}

func (c *Client) createWorkflowPodFromTemplate(ctx context.Context, workflowID string, now time.Time, leaseTTL time.Duration) (*corev1.Pod, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf("%s=warm-pool", labelComponent),
		Limit:         1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list warm pool pod templates: %w", err)
	}
	if len(pods.Items) == 0 {
		return nil, fmt.Errorf("no warm pool pod template available for workflow %s", workflowID)
	}

	template := pods.Items[0]
	namePart := workflowPodNamePart(workflowID)
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			GenerateName: fmt.Sprintf("workflow-%s-", namePart),
			Namespace:    c.namespace,
			Labels: map[string]string{
				labelComponent:  "workflow-sandbox",
				labelManagedBy:  "mcp-manager",
				labelWorkflowID: workflowID,
				labelStatus:     statusAssigned,
			},
			Annotations: map[string]string{
				annotationWorkflowAssignedAt: now.Format(time.RFC3339),
				annotationWorkflowLastUsedAt: now.Format(time.RFC3339),
				annotationWorkflowLeaseUntil: now.Add(leaseTTL).Format(time.RFC3339),
			},
		},
		Spec: template.Spec,
	}
	pod.Spec.NodeName = ""

	created, err := c.client.CoreV1().Pods(c.namespace).Create(ctx, pod, metav1.CreateOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to create workflow sandbox pod for %s: %w", workflowID, err)
	}
	return c.waitForPodRunning(ctx, created.Name, 120*time.Second)
}

// DeletePodForWorkflow deletes any pod labeled with the given workflow id.
// The DaemonSet/Deployment that manages the warm pool replenishes the
// deleted pod automatically; emptyDir state goes with the pod.
func (c *Client) DeletePodForWorkflow(ctx context.Context, workflowID string) error {
	selector := fmt.Sprintf("mcp.agentarea.io/workflow-id=%s", workflowID)
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: selector,
	})
	if err != nil {
		return fmt.Errorf("failed to list pods for workflow %s: %w", workflowID, err)
	}
	for _, pod := range pods.Items {
		if err := c.client.CoreV1().Pods(c.namespace).Delete(ctx, pod.Name, metav1.DeleteOptions{}); err != nil {
			return fmt.Errorf("failed to delete pod %s for workflow %s: %w", pod.Name, workflowID, err)
		}
	}
	return nil
}

// RetirePodForWorkflow moves workflow pods to an idle state and schedules
// garbage collection. A zero or negative TTL keeps the previous immediate
// deletion behavior.
func (c *Client) RetirePodForWorkflow(ctx context.Context, workflowID string, idleTTL time.Duration) error {
	if idleTTL <= 0 {
		return c.DeletePodForWorkflow(ctx, workflowID)
	}
	now := time.Now().UTC()
	selector := fmt.Sprintf("%s=%s", labelWorkflowID, workflowID)
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: selector,
	})
	if err != nil {
		return fmt.Errorf("failed to list pods for workflow %s: %w", workflowID, err)
	}
	for _, pod := range pods.Items {
		if pod.Labels == nil {
			pod.Labels = make(map[string]string)
		}
		if pod.Annotations == nil {
			pod.Annotations = make(map[string]string)
		}
		pod.Labels[labelStatus] = statusIdle
		pod.Annotations[annotationWorkflowIdleSince] = now.Format(time.RFC3339)
		pod.Annotations[annotationWorkflowCleanupAt] = now.Add(idleTTL).Format(time.RFC3339)
		delete(pod.Annotations, annotationWorkflowLeaseUntil)
		if _, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, &pod, metav1.UpdateOptions{}); err != nil {
			return fmt.Errorf("failed to mark pod %s idle for workflow %s: %w", pod.Name, workflowID, err)
		}
	}
	return nil
}

// TouchWorkflowPod extends the active lease for a workflow pod. The GC loop
// only deletes assigned pods after this lease expires, which prevents orphaned
// pods from living forever while leaving long-running tasks alone.
func (c *Client) TouchWorkflowPod(ctx context.Context, pod *corev1.Pod, leaseTTL time.Duration) error {
	if pod == nil || pod.Labels[labelWorkflowID] == "" || leaseTTL <= 0 {
		return nil
	}
	if pod.Annotations == nil {
		pod.Annotations = make(map[string]string)
	}
	now := time.Now().UTC()
	pod.Annotations[annotationWorkflowLastUsedAt] = now.Format(time.RFC3339)
	pod.Annotations[annotationWorkflowLeaseUntil] = now.Add(leaseTTL).Format(time.RFC3339)
	if _, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{}); err != nil {
		return fmt.Errorf("failed to extend workflow lease for pod %s: %w", pod.Name, err)
	}
	return nil
}

// DeleteExpiredWorkflowPods removes idle workflow sandboxes after their
// cleanup deadline and assigned sandboxes after their orphan lease expires.
func (c *Client) DeleteExpiredWorkflowPods(ctx context.Context, now time.Time) (int, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: labelWorkflowID,
	})
	if err != nil {
		return 0, fmt.Errorf("failed to list workflow sandbox pods: %w", err)
	}

	deleted := 0
	for _, pod := range pods.Items {
		status := pod.Labels[labelStatus]
		annotations := pod.Annotations
		if annotations == nil {
			annotations = map[string]string{}
		}

		var deadlineRaw string
		switch status {
		case statusIdle:
			deadlineRaw = annotations[annotationWorkflowCleanupAt]
		case statusAssigned:
			deadlineRaw = annotations[annotationWorkflowLeaseUntil]
		default:
			continue
		}
		if deadlineRaw == "" {
			continue
		}
		deadline, err := time.Parse(time.RFC3339, deadlineRaw)
		if err != nil || now.Before(deadline) {
			continue
		}
		if err := c.client.CoreV1().Pods(c.namespace).Delete(ctx, pod.Name, metav1.DeleteOptions{}); err != nil {
			return deleted, fmt.Errorf("failed to delete expired workflow sandbox pod %s: %w", pod.Name, err)
		}
		deleted++
	}
	return deleted, nil
}

// LabelStatefulPod labels an existing pod as stateful for a specific agent.
func (c *Client) LabelStatefulPod(ctx context.Context, pod *corev1.Pod, agentID string) (*corev1.Pod, error) {
	if pod.Labels == nil {
		pod.Labels = make(map[string]string)
	}
	pod.Labels["mcp.agentarea.io/agent-id"] = agentID
	pod.Labels["mcp.agentarea.io/type"] = "stateful"

	updated, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to label stateful pod: %w", err)
	}
	return updated, nil
}

// FindOrCreateStatefulPod returns the dedicated pod for agentID, creating one if needed.
// It waits up to 120 seconds for the pod to reach Running phase.
func (c *Client) FindOrCreateStatefulPod(ctx context.Context, agentID string) (*corev1.Pod, error) {
	selector := fmt.Sprintf("mcp.agentarea.io/agent-id=%s,mcp.agentarea.io/type=stateful", agentID)

	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: selector,
		Limit:         1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list stateful pods for agent %s: %w", agentID, err)
	}

	if len(pods.Items) > 0 {
		pod := &pods.Items[0]
		if pod.Status.Phase == corev1.PodRunning {
			return pod, nil
		}
		// Pod exists but not yet Running — wait for it.
		return c.waitForPodRunning(ctx, pod.Name, 120*time.Second)
	}

	// No pod found — clone a warm pool pod spec and create a stateful pod.
	warmPods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf("%s=warm-pool,%s=%s", labelComponent, labelStatus, statusWaiting),
		Limit:         1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list warm pool pods for cloning: %w", err)
	}
	if len(warmPods.Items) == 0 {
		return nil, fmt.Errorf("no warm pool pods available to clone for stateful agent %s", agentID)
	}

	template := warmPods.Items[0]

	// Build a new pod from the warm pool pod's spec.
	newPod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			GenerateName: fmt.Sprintf("stateful-%s-", agentID),
			Namespace:    c.namespace,
			Labels: map[string]string{
				"app.kubernetes.io/component":  "stateful-agent",
				"app.kubernetes.io/managed-by": "mcp-manager",
				"mcp.agentarea.io/agent-id":    agentID,
				"mcp.agentarea.io/type":        "stateful",
			},
		},
		Spec: template.Spec,
	}
	// Clear fields that must not be copied from an existing pod.
	newPod.Spec.NodeName = ""

	created, err := c.client.CoreV1().Pods(c.namespace).Create(ctx, newPod, metav1.CreateOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to create stateful pod for agent %s: %w", agentID, err)
	}

	return c.waitForPodRunning(ctx, created.Name, 120*time.Second)
}

// waitForPodRunning polls until the named pod is Running or the timeout elapses.
func (c *Client) waitForPodRunning(ctx context.Context, podName string, timeout time.Duration) (*corev1.Pod, error) {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		pod, err := c.client.CoreV1().Pods(c.namespace).Get(ctx, podName, metav1.GetOptions{})
		if err != nil {
			return nil, fmt.Errorf("failed to get pod %s: %w", podName, err)
		}
		if pod.Status.Phase == corev1.PodRunning && pod.Status.PodIP != "" {
			return pod, nil
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
	return nil, fmt.Errorf("timed out waiting for pod %s to become Running", podName)
}

// GetPoolStatus returns current warm pool status
func (c *Client) GetPoolStatus(ctx context.Context) (*PoolStatus, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf("%s=warm-pool", labelComponent),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list warm pods: %w", err)
	}

	status := &PoolStatus{
		Total:   len(pods.Items),
		ByPhase: make(map[string]int),
	}

	for _, pod := range pods.Items {
		status.ByPhase[string(pod.Status.Phase)]++

		if podStatus, ok := pod.Labels["mcp.agentarea.io/status"]; ok {
			switch podStatus {
			case "waiting":
				status.Waiting++
			case "activating":
				status.Activating++
			case "ready":
				status.Ready++
			case "assigned":
				status.Assigned++
			case "idle":
				status.Idle++
			}
		}
	}

	return status, nil
}

// PoolStatus holds warm pool statistics
type PoolStatus struct {
	Total      int
	Waiting    int
	Activating int
	Ready      int
	Assigned   int
	Idle       int
	ByPhase    map[string]int
}

func defaultWorkflowLeaseTTL() time.Duration {
	if value := os.Getenv("SANDBOX_WORKFLOW_LEASE_TTL"); value != "" {
		if duration, err := time.ParseDuration(value); err == nil && duration > 0 {
			return duration
		}
	}
	return 2 * time.Hour
}

func workflowPodNamePart(workflowID string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(workflowID) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '-' {
			b.WriteRune(r)
			continue
		}
		b.WriteRune('-')
	}
	value := strings.Trim(b.String(), "-")
	if value == "" {
		return "sandbox"
	}
	if len(value) > 32 {
		return value[:32]
	}
	return value
}
