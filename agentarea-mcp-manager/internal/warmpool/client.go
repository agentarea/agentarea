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
		LabelSelector: "app=mcp-warm-pool,mcp.agentarea.io/status=waiting",
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
	Env          map[string]string `json:"env"`
	Config       json.RawMessage   `json:"config,omitempty"`
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

// GetPoolStatus returns current warm pool status
func (c *Client) GetPoolStatus(ctx context.Context) (*PoolStatus, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: "app=mcp-warm-pool",
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
