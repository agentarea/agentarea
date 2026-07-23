package warmpool

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/workspace"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

const (
	labelComponent      = "app.kubernetes.io/component"
	labelManagedBy      = "app.kubernetes.io/managed-by"
	labelStatus         = "mcp.agentarea.io/status"
	labelTaskID         = "mcp.agentarea.io/task-id"
	labelPackageInstall = "mcp.agentarea.io/package-install"

	statusWaiting  = "waiting"
	statusAssigned = "assigned"
	statusIdle     = "idle"

	annotationTaskAssignedAt = "mcp.agentarea.io/task-assigned-at"
	annotationTaskLastUsedAt = "mcp.agentarea.io/task-last-used-at"
	annotationTaskLeaseUntil = "mcp.agentarea.io/task-lease-until"
	annotationTaskIdleSince  = "mcp.agentarea.io/task-idle-since"
	annotationTaskCleanupAt  = "mcp.agentarea.io/task-cleanup-at"
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

// FindAvailablePod finds a waiting warm pod built for the exact package-install
// profile. Profiles are isolation boundaries and are never downgraded.
func (c *Client) FindAvailablePod(ctx context.Context, packageInstall string) (*corev1.Pod, error) {
	if err := runtimeinfo.ValidatePackageInstall(packageInstall); err != nil {
		return nil, err
	}
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf(
			"%s=warm-pool,%s=%s,%s=%s",
			labelComponent,
			labelStatus,
			statusWaiting,
			labelPackageInstall,
			packageInstall,
		),
		Limit: 1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list warm pods: %w", err)
	}

	if len(pods.Items) == 0 {
		return nil, fmt.Errorf("no warm pods available for package_install profile %q", packageInstall)
	}

	return &pods.Items[0], nil
}

// FindRuntimeManifestPod selects a healthy data-plane pod for read-only
// capability discovery. Unlike assignment, discovery does not require a free
// waiting pod and never changes task or pool labels.
func (c *Client) FindRuntimeManifestPod(ctx context.Context, packageInstall string) (*corev1.Pod, error) {
	if err := runtimeinfo.ValidatePackageInstall(packageInstall); err != nil {
		return nil, err
	}
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf("%s=%s", labelPackageInstall, packageInstall),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list runtime pods: %w", err)
	}

	for i := range pods.Items {
		pod := &pods.Items[i]
		component := pod.Labels[labelComponent]
		if component != "warm-pool" && component != "workflow-sandbox" {
			continue
		}
		if pod.DeletionTimestamp != nil || pod.Status.Phase != corev1.PodRunning || pod.Status.PodIP == "" {
			continue
		}
		if !podConditionTrue(pod.Status.Conditions, corev1.PodReady) {
			continue
		}
		return pod, nil
	}

	return nil, fmt.Errorf("no ready runtime pods available for package_install profile %q", packageInstall)
}

func podConditionTrue(conditions []corev1.PodCondition, conditionType corev1.PodConditionType) bool {
	for _, condition := range conditions {
		if condition.Type == conditionType {
			return condition.Status == corev1.ConditionTrue
		}
	}
	return false
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
	token, err := activationauth.SignFromEnv(
		activationauth.ScopeActivate,
		activationauth.Identity{
			WorkspaceID:  "mcp-control",
			TaskID:       req.MCPImageHash,
			Generation:   0,
			FencingToken: 1,
		},
		activationauth.BodySHA256(body),
		time.Now(),
	)
	if err != nil {
		return fmt.Errorf("create activation authorization: %w", err)
	}
	httpReq.Header.Set("Authorization", "Bearer "+token)

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

// ExecuteRequest holds manifest-backed command execution parameters.
//
// TaskID and WorkspaceManifestRef identify the canonical task workspace.
// The activation service hydrates that immutable manifest before execution;
// TaskID also selects and leases the task's warm pod.
type ExecuteRequest struct {
	CommandBody          string                 `json:"command_body,omitempty"`
	CommandPath          string                 `json:"command_path,omitempty"`
	PackageInstall       string                 `json:"package_install"`
	ArtifactPaths        []string               `json:"artifact_paths,omitempty"`
	TimeoutSeconds       int                    `json:"timeout_seconds,omitempty"`
	StdoutMaxBytes       int64                  `json:"stdout_max_bytes,omitempty"`
	StderrMaxBytes       int64                  `json:"stderr_max_bytes,omitempty"`
	WorkflowID           string                 `json:"workflow_id,omitempty"`
	TaskID               string                 `json:"task_id,omitempty"`
	WorkspaceID          string                 `json:"workspace_id,omitempty"`
	WorkspaceManifestRef *workspace.ManifestRef `json:"workspace_manifest_ref,omitempty"`
	WorkspaceHydration   *workspace.Hydration   `json:"workspace_hydration,omitempty"`
}

// MaxCommandBodyBytes bounds the inline command carried in an execution request.
const MaxCommandBodyBytes = 256 * 1024

// SandboxArtifact is a file produced by a sandbox command and requested by the caller.
type SandboxArtifact struct {
	Path        string `json:"path"`
	Name        string `json:"name,omitempty"`
	ContentType string `json:"content_type,omitempty"`
	Size        int64  `json:"size,omitempty"`
	SHA256      string `json:"sha256,omitempty"`
	Error       string `json:"error,omitempty"`
}

// ExecuteResponse holds script execution result
type ExecuteResponse struct {
	Stdout           string                       `json:"stdout,omitempty"`
	Stderr           string                       `json:"stderr,omitempty"`
	StdoutRef        *workspace.Entry             `json:"stdout_ref,omitempty"`
	StderrRef        *workspace.Entry             `json:"stderr_ref,omitempty"`
	StdoutTruncated  bool                         `json:"stdout_truncated,omitempty"`
	StderrTruncated  bool                         `json:"stderr_truncated,omitempty"`
	ExitCode         int                          `json:"exit_code"`
	ExecutionTimeMs  int64                        `json:"execution_time_ms"`
	Artifacts        []SandboxArtifact            `json:"artifacts,omitempty"`
	WorkspaceChanges []workspace.ChangeDescriptor `json:"workspace_changes,omitempty"`
}

func (r *ExecuteRequest) UnmarshalJSON(data []byte) error {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for _, field := range []string{"args", "env", "script", "input_files", "content_base64", "script_content", "script_name"} {
		if _, exists := fields[field]; exists {
			return fmt.Errorf("unsupported_contract_version: inline commands and files are forbidden; use command_path and workspace_manifest_ref")
		}
	}
	type requestAlias ExecuteRequest
	var decoded requestAlias
	if err := json.Unmarshal(data, &decoded); err != nil {
		return err
	}
	*r = ExecuteRequest(decoded)
	return nil
}

// ExecuteInPod sends one manifest-backed task execution to its assigned warm pod.
func (c *Client) ExecuteInPod(ctx context.Context, pod *corev1.Pod, req ExecuteRequest) (*ExecuteResponse, error) {
	podIP := pod.Status.PodIP
	if podIP == "" {
		return nil, fmt.Errorf("pod has no IP address")
	}
	return PostExecute(ctx, fmt.Sprintf("http://%s:8080/execute", podIP), req, c.timeout)
}

func (c *Client) RuntimeManifestInPod(ctx context.Context, pod *corev1.Pod, packageInstall string) (*runtimeinfo.Manifest, error) {
	if pod.Status.PodIP == "" {
		return nil, fmt.Errorf("pod has no IP address")
	}
	return GetRuntimeManifest(ctx, fmt.Sprintf("http://%s:8080", pod.Status.PodIP), c.timeout, packageInstall)
}

func (c *Client) WritebackInPod(ctx context.Context, pod *corev1.Pod, req workspace.WritebackRequest) (*workspace.WritebackResponse, error) {
	if pod.Status.PodIP == "" {
		return nil, fmt.Errorf("pod has no IP address")
	}
	return PostWriteback(ctx, fmt.Sprintf("http://%s:8080", pod.Status.PodIP), req, c.timeout)
}

// PostExecute sends an ExecuteRequest to a sandbox executor's /execute endpoint
// and returns the parsed result. The endpoint is the same whether it is a
// Kubernetes warm pod (warm-pool data plane) or the dev/compose sandbox-executor
// container, so both backends share this transport.
func PostExecute(ctx context.Context, executeURL string, req ExecuteRequest, baseTimeout time.Duration) (*ExecuteResponse, error) {
	if err := runtimeinfo.ValidatePackageInstall(req.PackageInstall); err != nil {
		return nil, err
	}
	if req.CommandBody == "" {
		return nil, fmt.Errorf("command_body is required")
	}
	if len(req.CommandBody) > MaxCommandBodyBytes {
		return nil, fmt.Errorf("command_body exceeds %d bytes", MaxCommandBodyBytes)
	}
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
	token, err := activationauth.SignFromEnv(
		activationauth.ScopeExecute,
		activationauth.Identity{
			WorkspaceID:  req.WorkspaceID,
			TaskID:       req.TaskID,
			Generation:   0,
			FencingToken: 1,
		},
		activationauth.BodySHA256(body),
		time.Now(),
	)
	if err != nil {
		return nil, fmt.Errorf("create activation authorization: %w", err)
	}
	httpReq.Header.Set("Authorization", "Bearer "+token)

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

func PostWriteback(ctx context.Context, executeURL string, req workspace.WritebackRequest, baseTimeout time.Duration) (*workspace.WritebackResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal writeback request: %w", err)
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(executeURL, "/")+"/workspace/writeback", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("failed to create writeback request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	token, err := activationauth.SignFromEnv(
		activationauth.ScopeWriteback,
		activationauth.Identity{
			WorkspaceID:  req.WorkspaceID,
			TaskID:       req.TaskID,
			Generation:   req.BaseGeneration,
			FencingToken: req.FencingToken,
		},
		activationauth.BodySHA256(body),
		time.Now(),
	)
	if err != nil {
		return nil, fmt.Errorf("create activation authorization: %w", err)
	}
	httpReq.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{Timeout: baseTimeout}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("writeback request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("writeback returned status %d", resp.StatusCode)
	}
	var result workspace.WritebackResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode writeback response: %w", err)
	}
	return &result, nil
}

func GetRuntimeManifest(ctx context.Context, baseURL string, timeout time.Duration, packageInstall string) (*runtimeinfo.Manifest, error) {
	if err := runtimeinfo.ValidatePackageInstall(packageInstall); err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(baseURL, "/")+"/runtime/manifest", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create runtime manifest request: %w", err)
	}
	query := request.URL.Query()
	query.Set("package_install", packageInstall)
	request.URL.RawQuery = query.Encode()
	client := &http.Client{Timeout: timeout}
	response, err := client.Do(request)
	if err != nil {
		return nil, fmt.Errorf("runtime manifest request failed: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("runtime manifest returned status %d", response.StatusCode)
	}
	var manifest runtimeinfo.Manifest
	decoder := json.NewDecoder(response.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&manifest); err != nil {
		return nil, fmt.Errorf("failed to decode runtime manifest: %w", err)
	}
	if err := manifest.Validate(); err != nil {
		return nil, fmt.Errorf("invalid runtime manifest: %w", err)
	}
	if !manifest.SupportsPackageInstall(packageInstall) {
		return nil, fmt.Errorf(
			"runtime manifest does not support package_install profile %q",
			packageInstall,
		)
	}
	return &manifest, nil
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

// FindOrAssignPodForTask returns the pod assigned to a task identity,
// allocating one if needed. Canonical state is always rehydrated
// from the immutable task manifest; pod stickiness only avoids cold starts.
func (c *Client) FindOrAssignPodForTask(ctx context.Context, taskID, packageInstall string) (*corev1.Pod, error) {
	if err := runtimeinfo.ValidatePackageInstall(packageInstall); err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	selector := fmt.Sprintf("%s=%s", labelTaskID, taskID)
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: selector,
		Limit:         1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list pods for task %s: %w", taskID, err)
	}
	if len(pods.Items) > 0 {
		pod := &pods.Items[0]
		assignedProfile := pod.Labels[labelPackageInstall]
		if assignedProfile != packageInstall {
			return nil, fmt.Errorf(
				"task %s is assigned to package_install profile %q, requested %q",
				taskID,
				assignedProfile,
				packageInstall,
			)
		}
		if pod.Labels[labelStatus] == statusIdle {
			return c.markTaskAssigned(ctx, pod, taskID, packageInstall, now, defaultTaskLeaseTTL())
		}
		if err := c.TouchTaskPod(ctx, pod, defaultTaskLeaseTTL()); err != nil {
			return nil, err
		}
		return pod, nil
	}

	pod, err := c.FindAvailablePod(ctx, packageInstall)
	if err != nil {
		return c.createTaskPodFromTemplate(ctx, taskID, packageInstall, now, defaultTaskLeaseTTL())
	}
	return c.markTaskAssigned(ctx, pod, taskID, packageInstall, now, defaultTaskLeaseTTL())
}

// FindPodForTask returns an existing task pod without selecting or cloning a
// runtime profile. Writeback must target the same pod that executed the command;
// creating a replacement would lose its workspace changes.
func (c *Client) FindPodForTask(ctx context.Context, taskID string) (*corev1.Pod, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf("%s=%s", labelTaskID, taskID),
		Limit:         1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list pods for task %s: %w", taskID, err)
	}
	if len(pods.Items) == 0 {
		return nil, fmt.Errorf("no assigned sandbox pod found for task %s", taskID)
	}
	pod := &pods.Items[0]
	packageInstall := pod.Labels[labelPackageInstall]
	if err := runtimeinfo.ValidatePackageInstall(packageInstall); err != nil {
		return nil, fmt.Errorf("task %s pod has invalid runtime profile: %w", taskID, err)
	}
	if pod.Labels[labelStatus] == statusIdle {
		return c.markTaskAssigned(ctx, pod, taskID, packageInstall, time.Now().UTC(), defaultTaskLeaseTTL())
	}
	if err := c.TouchTaskPod(ctx, pod, defaultTaskLeaseTTL()); err != nil {
		return nil, err
	}
	return pod, nil
}

func (c *Client) markTaskAssigned(ctx context.Context, pod *corev1.Pod, taskID, packageInstall string, now time.Time, leaseTTL time.Duration) (*corev1.Pod, error) {
	if pod.Labels == nil {
		pod.Labels = make(map[string]string)
	}
	if pod.Annotations == nil {
		pod.Annotations = make(map[string]string)
	}
	if _, ok := pod.Annotations[annotationTaskAssignedAt]; !ok {
		pod.Annotations[annotationTaskAssignedAt] = now.Format(time.RFC3339)
	}
	pod.Labels[labelTaskID] = taskID
	pod.Labels[labelPackageInstall] = packageInstall
	pod.Labels[labelStatus] = statusAssigned
	pod.Annotations[annotationTaskLastUsedAt] = now.Format(time.RFC3339)
	pod.Annotations[annotationTaskLeaseUntil] = now.Add(leaseTTL).Format(time.RFC3339)
	delete(pod.Annotations, annotationTaskIdleSince)
	delete(pod.Annotations, annotationTaskCleanupAt)

	updated, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to assign pod to task %s: %w", taskID, err)
	}
	return updated, nil
}

func (c *Client) createTaskPodFromTemplate(ctx context.Context, taskID, packageInstall string, now time.Time, leaseTTL time.Duration) (*corev1.Pod, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf("%s=warm-pool,%s=%s", labelComponent, labelPackageInstall, packageInstall),
		Limit:         1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list warm pool pod templates: %w", err)
	}
	if len(pods.Items) == 0 {
		return nil, fmt.Errorf("no warm pool pod template available for task %s with package_install profile %q", taskID, packageInstall)
	}

	template := pods.Items[0]
	pod := taskPodFromTemplate(template, c.namespace, taskID, now, leaseTTL)

	created, err := c.client.CoreV1().Pods(c.namespace).Create(ctx, pod, metav1.CreateOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to create task sandbox pod for %s: %w", taskID, err)
	}
	return c.waitForPodRunning(ctx, created.Name, 120*time.Second)
}

func taskPodFromTemplate(template corev1.Pod, namespace, taskID string, now time.Time, leaseTTL time.Duration) *corev1.Pod {
	labels := maps.Clone(template.Labels)
	if labels == nil {
		labels = make(map[string]string)
	}
	labels[labelComponent] = "workflow-sandbox"
	labels[labelManagedBy] = "mcp-manager"
	labels[labelTaskID] = taskID
	labels[labelStatus] = statusAssigned

	annotations := maps.Clone(template.Annotations)
	if annotations == nil {
		annotations = make(map[string]string)
	}
	annotations[annotationTaskAssignedAt] = now.Format(time.RFC3339)
	annotations[annotationTaskLastUsedAt] = now.Format(time.RFC3339)
	annotations[annotationTaskLeaseUntil] = now.Add(leaseTTL).Format(time.RFC3339)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			GenerateName: fmt.Sprintf("task-%s-", taskPodNamePart(taskID)),
			Namespace:    namespace,
			Labels:       labels,
			Annotations:  annotations,
		},
		Spec: *template.Spec.DeepCopy(),
	}
	automountServiceAccountToken := false
	pod.Spec.AutomountServiceAccountToken = &automountServiceAccountToken
	pod.Spec.NodeName = ""
	return pod
}

// DeletePodForTask deletes any pod labeled with the given task id.
// The DaemonSet/Deployment that manages the warm pool replenishes the
// deleted pod automatically; emptyDir state goes with the pod.
func (c *Client) DeletePodForTask(ctx context.Context, taskID string) error {
	selector := fmt.Sprintf("%s=%s", labelTaskID, taskID)
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: selector,
	})
	if err != nil {
		return fmt.Errorf("failed to list pods for task %s: %w", taskID, err)
	}
	for _, pod := range pods.Items {
		if err := c.client.CoreV1().Pods(c.namespace).Delete(ctx, pod.Name, metav1.DeleteOptions{}); err != nil {
			return fmt.Errorf("failed to delete pod %s for task %s: %w", pod.Name, taskID, err)
		}
	}
	return nil
}

// RetirePodForTask moves task pods to an idle state and schedules
// garbage collection. A zero or negative TTL keeps the previous immediate
// deletion behavior.
func (c *Client) RetirePodForTask(ctx context.Context, taskID string, idleTTL time.Duration) error {
	if idleTTL <= 0 {
		return c.DeletePodForTask(ctx, taskID)
	}
	now := time.Now().UTC()
	selector := fmt.Sprintf("%s=%s", labelTaskID, taskID)
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: selector,
	})
	if err != nil {
		return fmt.Errorf("failed to list pods for task %s: %w", taskID, err)
	}
	for _, pod := range pods.Items {
		if pod.Labels == nil {
			pod.Labels = make(map[string]string)
		}
		if pod.Annotations == nil {
			pod.Annotations = make(map[string]string)
		}
		pod.Labels[labelStatus] = statusIdle
		pod.Annotations[annotationTaskIdleSince] = now.Format(time.RFC3339)
		pod.Annotations[annotationTaskCleanupAt] = now.Add(idleTTL).Format(time.RFC3339)
		delete(pod.Annotations, annotationTaskLeaseUntil)
		if _, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, &pod, metav1.UpdateOptions{}); err != nil {
			return fmt.Errorf("failed to mark pod %s idle for task %s: %w", pod.Name, taskID, err)
		}
	}
	return nil
}

// TouchTaskPod extends the active lease for a task pod. The GC loop
// only deletes assigned pods after this lease expires, which prevents orphaned
// pods from living forever while leaving long-running tasks alone.
func (c *Client) TouchTaskPod(ctx context.Context, pod *corev1.Pod, leaseTTL time.Duration) error {
	if pod == nil || pod.Labels[labelTaskID] == "" || leaseTTL <= 0 {
		return nil
	}
	if pod.Annotations == nil {
		pod.Annotations = make(map[string]string)
	}
	now := time.Now().UTC()
	pod.Annotations[annotationTaskLastUsedAt] = now.Format(time.RFC3339)
	pod.Annotations[annotationTaskLeaseUntil] = now.Add(leaseTTL).Format(time.RFC3339)
	if _, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{}); err != nil {
		return fmt.Errorf("failed to extend task lease for pod %s: %w", pod.Name, err)
	}
	return nil
}

// DeleteExpiredTaskPods removes idle task sandboxes after their cleanup
// deadline and assigned sandboxes after their orphan lease expires.
func (c *Client) DeleteExpiredTaskPods(ctx context.Context, now time.Time) (int, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: labelTaskID,
	})
	if err != nil {
		return 0, fmt.Errorf("failed to list task sandbox pods: %w", err)
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
			deadlineRaw = annotations[annotationTaskCleanupAt]
		case statusAssigned:
			deadlineRaw = annotations[annotationTaskLeaseUntil]
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
			return deleted, fmt.Errorf("failed to delete expired task sandbox pod %s: %w", pod.Name, err)
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
		LabelSelector: fmt.Sprintf(
			"%s=warm-pool,%s=%s,%s=%s",
			labelComponent,
			labelStatus,
			statusWaiting,
			labelPackageInstall,
			runtimeinfo.PackageInstallAllowed,
		),
		Limit: 1,
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
				labelPackageInstall:            runtimeinfo.PackageInstallAllowed,
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

func defaultTaskLeaseTTL() time.Duration {
	if value := os.Getenv("SANDBOX_TASK_LEASE_TTL"); value != "" {
		if duration, err := time.ParseDuration(value); err == nil && duration > 0 {
			return duration
		}
	}
	return 2 * time.Hour
}

func taskPodNamePart(taskID string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(taskID) {
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
