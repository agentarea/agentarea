package warmpool

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
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
		timeout:   30 * time.Second,
	}
}

// FindAvailablePod finds a warm pod in "waiting" state
func (c *Client) FindAvailablePod(ctx context.Context) (*corev1.Pod, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: "app.kubernetes.io/component=warm-pool,mcp.agentarea.io/status=waiting",
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

// ExecuteRequest holds script execution parameters
type ExecuteRequest struct {
	ScriptContent  string            `json:"script_content"`
	ScriptName     string            `json:"script_name"`
	Args           []string          `json:"args,omitempty"`
	Env            map[string]string `json:"env,omitempty"`
	TimeoutSeconds int              `json:"timeout_seconds,omitempty"`
}

// ExecuteResponse holds script execution result
type ExecuteResponse struct {
	Stdout          string `json:"stdout"`
	Stderr          string `json:"stderr"`
	ExitCode        int    `json:"exit_code"`
	ExecutionTimeMs int64  `json:"execution_time_ms"`
}

// ExecuteInPod sends a script execution request to a warm pod.
// The pod stays in "waiting" state — no assignment needed for stateless execution.
func (c *Client) ExecuteInPod(ctx context.Context, pod *corev1.Pod, req ExecuteRequest) (*ExecuteResponse, error) {
	podIP := pod.Status.PodIP
	if podIP == "" {
		return nil, fmt.Errorf("pod has no IP address")
	}

	url := fmt.Sprintf("http://%s:8080/execute", podIP)

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	timeout := c.timeout
	if req.TimeoutSeconds > 0 {
		// Add buffer for network overhead
		timeout = time.Duration(req.TimeoutSeconds+5) * time.Second
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(body))
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
		LabelSelector: "app.kubernetes.io/component=warm-pool,mcp.agentarea.io/status=waiting",
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
		LabelSelector: "app.kubernetes.io/component=warm-pool",
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list warm pods: %w", err)
	}

	status := &PoolStatus{
		Total: len(pods.Items),
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
	ByPhase    map[string]int
}
