package warmpool

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"maps"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/execsupervisor"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	"github.com/agentarea/mcp-manager/internal/workspace"
	"github.com/google/uuid"
	corev1 "k8s.io/api/core/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

const (
	labelComponent   = "app.kubernetes.io/component"
	labelManagedBy   = "app.kubernetes.io/managed-by"
	labelStatus      = "mcp.agentarea.io/status"
	labelTaskBinding = "mcp.agentarea.io/task-binding"

	statusWaiting  = "waiting"
	statusAssigned = "assigned"
	statusIdle     = "idle"

	annotationTaskAssignedAt            = "mcp.agentarea.io/task-assigned-at"
	annotationTaskLastUsedAt            = "mcp.agentarea.io/task-last-used-at"
	annotationTaskLeaseUntil            = "mcp.agentarea.io/task-lease-until"
	annotationTaskIdleSince             = "mcp.agentarea.io/task-idle-since"
	annotationTaskCleanupAt             = "mcp.agentarea.io/task-cleanup-at"
	annotationWorkspaceID               = "mcp.agentarea.io/workspace-id"
	annotationTaskID                    = "mcp.agentarea.io/task-id"
	annotationHydrationRev              = "mcp.agentarea.io/hydration-revision"
	annotationHydrationIncarnation      = "mcp.agentarea.io/hydration-executor-incarnation"
	annotationHydrationClaim            = "mcp.agentarea.io/hydration-claim"
	annotationHydrationUntil            = "mcp.agentarea.io/hydration-claim-until"
	annotationHydrationClaimIncarnation = "mcp.agentarea.io/hydration-claim-executor-incarnation"
	annotationTaskOperations            = "mcp.agentarea.io/task-operations"
)

// TaskOperation fences one live command or file stream against task
// retirement. The UID prevents an old operation from mutating a replacement
// pod with the same deterministic name.
type TaskOperation struct {
	PodName             string
	PodUID              string
	Binding             string
	Token               string
	ExecutorIncarnation string
}

type TaskPodInfo struct {
	ID          string
	WorkspaceID string
	TaskID      string
	State       string
	CreatedAt   time.Time
	ExpiresAt   *time.Time
	Resources   map[string]string
	Isolation   string
}

// Client manages warm pool operations
type Client struct {
	client                     kubernetes.Interface
	namespace                  string
	timeout                    time.Duration
	taskLeaseTTL               time.Duration
	observeExecutorIncarnation func(context.Context, *corev1.Pod) (string, error)
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
func NewClient(client kubernetes.Interface, namespace string, taskLeaseTTL time.Duration) *Client {
	clientInstance := &Client{
		client:       client,
		namespace:    namespace,
		timeout:      120 * time.Second,
		taskLeaseTTL: taskLeaseTTL,
	}
	clientInstance.observeExecutorIncarnation = func(ctx context.Context, pod *corev1.Pod) (string, error) {
		return GetExecutorIncarnation(ctx, fmt.Sprintf("http://%s:8080", pod.Status.PodIP), 10*time.Second)
	}
	return clientInstance
}

// FindAvailablePod finds a waiting warm pod from the configured runtime pool.
func (c *Client) FindAvailablePod(ctx context.Context) (*corev1.Pod, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf(
			"%s=warm-pool,%s=%s",
			labelComponent,
			labelStatus,
			statusWaiting,
		),
		Limit: 1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list warm pods: %w", err)
	}

	if len(pods.Items) == 0 {
		return nil, fmt.Errorf("no warm pods available")
	}

	return &pods.Items[0], nil
}

// FindRuntimeManifestPod selects a healthy data-plane pod for read-only
// capability discovery. Unlike assignment, discovery does not require a free
// waiting pod and never changes task or pool labels.
func (c *Client) FindRuntimeManifestPod(ctx context.Context) (*corev1.Pod, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: labelComponent,
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

	return nil, fmt.Errorf("no ready runtime pods available")
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

type ExecuteRequest = sandboxcontract.ExecuteRequest
type ExecuteResponse = sandboxcontract.ExecuteResponse
type SandboxArtifact = sandboxcontract.SandboxArtifact

const MaxCommandBodyBytes = sandboxcontract.MaxCommandBodyBytes

// ExecuteInPod sends one manager-prepared task execution to its assigned warm pod.
func (c *Client) ExecuteInPod(ctx context.Context, pod *corev1.Pod, req ExecuteRequest) (*ExecuteResponse, error) {
	podIP := pod.Status.PodIP
	if podIP == "" {
		return nil, fmt.Errorf("pod has no IP address")
	}
	return PostExecute(ctx, fmt.Sprintf("http://%s:8080/execute", podIP), req, c.timeout)
}

func (c *Client) RuntimeManifestInPod(ctx context.Context, pod *corev1.Pod) (*runtimeinfo.Manifest, error) {
	if pod.Status.PodIP == "" {
		return nil, fmt.Errorf("pod has no IP address")
	}
	return GetRuntimeManifest(ctx, fmt.Sprintf("http://%s:8080", pod.Status.PodIP), c.timeout)
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

	timeout := executeTransportTimeout(req.TimeoutSeconds, baseTimeout)

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
	if executorUnsafe(resp) {
		return nil, ErrExecutorUnsafe
	}

	if resp.StatusCode == http.StatusPreconditionFailed {
		return nil, ErrExecutorIncarnationChanged
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("execute returned status %d", resp.StatusCode)
	}

	var result ExecuteResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &result, nil
}

func executeTransportTimeout(commandTimeoutSeconds int, baseTimeout time.Duration) time.Duration {
	if commandTimeoutSeconds <= 0 {
		return baseTimeout
	}
	// The transport must outlive command timeout, descendant drain, durable
	// status publication, and a final network margin. Killing the HTTP request
	// earlier would kill the supervisor before it can prove quiescence.
	return time.Duration(commandTimeoutSeconds)*time.Second + execsupervisor.TransportGrace
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

type FilePutRequest = sandboxcontract.FilePutRequest
type FilePutResponse = sandboxcontract.FilePutResponse
type FileGetResponse = sandboxcontract.FileGetResponse

// FileTransferRequest identifies a streamed write into a task workspace. The
// body travels as application/octet-stream; its immutable size/hash identity is
// signed into the executor request instead of serializing bytes through JSON.
type FileTransferRequest struct {
	WorkspaceID         string
	TaskID              string
	ExecutorIncarnation string
	Path                string
	Size                int64
	SHA256              string
	Mode                uint32
}

// FileDownload is a streamed sandbox file. Closing Content releases the
// provider connection; callers must never persist it in workflow state.
type FileDownload struct {
	Content io.ReadCloser
	Size    int64
	Mode    uint32
}

type FileListResponse = sandboxcontract.FileListResponse

// ErrFileNotFound signals that a requested sandbox file does not exist.
var ErrFileNotFound = sandboxcontract.ErrFileNotFound

// ErrTaskWorkspaceGone signals that the ephemeral task directory has already
// been reclaimed while the durable inputs/artifacts remain available.
var ErrTaskWorkspaceGone = fmt.Errorf("sandbox task workspace gone")

// ErrExecutorIncarnationChanged means the Docker development executor
// restarted after hydration was observed but before the requested operation.
var ErrExecutorIncarnationChanged = fmt.Errorf("sandbox executor incarnation changed")

// ErrExecutorUnsafe means the activation service destructively discarded its
// workspace after it could no longer prove a reusable execution state. The
// caller must invalidate the exact runtime binding before another demand.
var ErrExecutorUnsafe = errors.New("sandbox executor declared its workspace unsafe")

func executorUnsafe(response *http.Response) bool {
	return response != nil && strings.EqualFold(response.Header.Get("X-Agentarea-Executor-Unsafe"), "true")
}

// PutFile writes a file into the task workspace on the executor's filesystem —
// the same filesystem /execute (bash) uses — signing a ScopeFiles token so the
// activation secret stays control-plane side.
func PutFile(ctx context.Context, baseURL string, req FilePutRequest, timeout time.Duration) (*FilePutResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal file put request: %w", err)
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPut, strings.TrimRight(baseURL, "/")+"/files", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("failed to create file put request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	if err := signFilesRequest(httpReq, req.WorkspaceID, req.TaskID, activationauth.BodySHA256(body)); err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: timeout}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("file put request failed: %w", err)
	}
	defer resp.Body.Close()
	if executorUnsafe(resp) {
		return nil, ErrExecutorUnsafe
	}
	if resp.StatusCode == http.StatusPreconditionFailed {
		return nil, ErrExecutorIncarnationChanged
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("file put returned status %d", resp.StatusCode)
	}
	var result FilePutResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode file put response: %w", err)
	}
	return &result, nil
}

// PutFileStream writes a file without buffering or base64 expansion. The
// manager has already admitted Size against task policy; the executor verifies
// the signed SHA-256 while atomically replacing the destination.
func PutFileStream(ctx context.Context, baseURL string, req FileTransferRequest, content io.Reader, timeout time.Duration) (*FilePutResponse, error) {
	if req.WorkspaceID == "" || req.TaskID == "" || req.Path == "" || req.Size < 0 || content == nil {
		return nil, fmt.Errorf("workspace_id, task_id, path, non-negative size, and content are required")
	}
	digest, err := hex.DecodeString(req.SHA256)
	if err != nil || len(digest) != 32 || req.SHA256 != strings.ToLower(req.SHA256) {
		return nil, fmt.Errorf("file transfer requires a lowercase SHA-256 digest")
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPut, strings.TrimRight(baseURL, "/")+"/files/content", io.NopCloser(content))
	if err != nil {
		return nil, fmt.Errorf("failed to create streamed file put request: %w", err)
	}
	query := httpReq.URL.Query()
	query.Set("workspace_id", req.WorkspaceID)
	query.Set("task_id", req.TaskID)
	if req.ExecutorIncarnation != "" {
		query.Set("executor_incarnation", req.ExecutorIncarnation)
	}
	query.Set("path", req.Path)
	query.Set("size", strconv.FormatInt(req.Size, 10))
	query.Set("sha256", req.SHA256)
	query.Set("mode", strconv.FormatUint(uint64(req.Mode), 8))
	httpReq.URL.RawQuery = query.Encode()
	httpReq.ContentLength = req.Size
	httpReq.Header.Set("Content-Type", "application/octet-stream")
	if err := signFilesRequest(httpReq, req.WorkspaceID, req.TaskID, activationauth.BoundTransferSHA256(http.MethodPut, req.Path, req.Size, req.Mode, req.SHA256, req.ExecutorIncarnation)); err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: timeout}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("streamed file put request failed: %w", err)
	}
	defer resp.Body.Close()
	if executorUnsafe(resp) {
		return nil, ErrExecutorUnsafe
	}
	if resp.StatusCode == http.StatusPreconditionFailed {
		return nil, ErrExecutorIncarnationChanged
	}
	if resp.StatusCode != http.StatusOK {
		message, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("streamed file put returned status %d: %s", resp.StatusCode, strings.TrimSpace(string(message)))
	}
	var result FilePutResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode streamed file put response: %w", err)
	}
	return &result, nil
}

// OpenFile streams a file from the executor. The response body remains open so
// a caller can copy it directly to S3 or an HTTP response with constant memory.
func OpenFile(ctx context.Context, baseURL, workspaceID, taskID, path string, timeout time.Duration) (*FileDownload, error) {
	return OpenFileForIncarnation(ctx, baseURL, workspaceID, taskID, path, "", timeout)
}

func OpenFileForIncarnation(ctx context.Context, baseURL, workspaceID, taskID, path, executorIncarnation string, timeout time.Duration) (*FileDownload, error) {
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(baseURL, "/")+"/files/content", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create streamed file get request: %w", err)
	}
	query := httpReq.URL.Query()
	query.Set("workspace_id", workspaceID)
	query.Set("task_id", taskID)
	query.Set("path", path)
	if executorIncarnation != "" {
		query.Set("executor_incarnation", executorIncarnation)
	}
	httpReq.URL.RawQuery = query.Encode()
	if err := signFilesRequest(httpReq, workspaceID, taskID, activationauth.BoundTransferSHA256(http.MethodGet, path, -1, 0, activationauth.BodySHA256(nil), executorIncarnation)); err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: timeout}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("streamed file get request failed: %w", err)
	}
	if executorUnsafe(resp) {
		resp.Body.Close()
		return nil, ErrExecutorUnsafe
	}
	if resp.StatusCode == http.StatusNotFound {
		resp.Body.Close()
		return nil, ErrFileNotFound
	}
	if resp.StatusCode == http.StatusGone {
		resp.Body.Close()
		return nil, ErrTaskWorkspaceGone
	}
	if resp.StatusCode == http.StatusPreconditionFailed {
		resp.Body.Close()
		return nil, ErrExecutorIncarnationChanged
	}
	if resp.StatusCode != http.StatusOK {
		message, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		resp.Body.Close()
		return nil, fmt.Errorf("streamed file get returned status %d: %s", resp.StatusCode, strings.TrimSpace(string(message)))
	}
	if resp.ContentLength < 0 {
		resp.Body.Close()
		return nil, fmt.Errorf("streamed file get omitted Content-Length")
	}
	mode, err := strconv.ParseUint(resp.Header.Get("X-AgentArea-File-Mode"), 8, 32)
	if err != nil || mode&^uint64(0o777) != 0 {
		resp.Body.Close()
		return nil, fmt.Errorf("streamed file get returned invalid mode")
	}
	return &FileDownload{Content: resp.Body, Size: resp.ContentLength, Mode: uint32(mode)}, nil
}

// GetFile reads a file from the task workspace. It returns ErrFileNotFound when
// the executor reports a 404 so callers can distinguish "missing" from failure.
func GetFile(ctx context.Context, baseURL, workspaceID, taskID, path string, timeout time.Duration) (*FileGetResponse, error) {
	return GetFileForIncarnation(ctx, baseURL, workspaceID, taskID, path, "", timeout)
}

func GetFileForIncarnation(ctx context.Context, baseURL, workspaceID, taskID, path, executorIncarnation string, timeout time.Duration) (*FileGetResponse, error) {
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(baseURL, "/")+"/files", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create file get request: %w", err)
	}
	query := httpReq.URL.Query()
	query.Set("workspace_id", workspaceID)
	query.Set("task_id", taskID)
	query.Set("path", path)
	if executorIncarnation != "" {
		query.Set("executor_incarnation", executorIncarnation)
	}
	httpReq.URL.RawQuery = query.Encode()
	if err := signFilesRequest(httpReq, workspaceID, taskID, activationauth.BoundTransferSHA256(http.MethodGet, "file:"+path, -1, 0, activationauth.BodySHA256(nil), executorIncarnation)); err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: timeout}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("file get request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return nil, ErrFileNotFound
	}
	if resp.StatusCode == http.StatusGone {
		return nil, ErrTaskWorkspaceGone
	}
	if resp.StatusCode == http.StatusPreconditionFailed {
		return nil, ErrExecutorIncarnationChanged
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("file get returned status %d", resp.StatusCode)
	}
	var result FileGetResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode file get response: %w", err)
	}
	return &result, nil
}

// ListFiles lists regular files under prefix in the task workspace.
func ListFiles(ctx context.Context, baseURL, workspaceID, taskID, prefix string, timeout time.Duration) (*FileListResponse, error) {
	return ListFilesForIncarnation(ctx, baseURL, workspaceID, taskID, prefix, "", timeout)
}

func ListFilesForIncarnation(ctx context.Context, baseURL, workspaceID, taskID, prefix, executorIncarnation string, timeout time.Duration) (*FileListResponse, error) {
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(baseURL, "/")+"/files", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create file list request: %w", err)
	}
	query := httpReq.URL.Query()
	query.Set("workspace_id", workspaceID)
	query.Set("task_id", taskID)
	query.Set("list", prefix)
	if executorIncarnation != "" {
		query.Set("executor_incarnation", executorIncarnation)
	}
	httpReq.URL.RawQuery = query.Encode()
	if err := signFilesRequest(httpReq, workspaceID, taskID, activationauth.BoundTransferSHA256(http.MethodGet, "list:"+prefix, -1, 0, activationauth.BodySHA256(nil), executorIncarnation)); err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: timeout}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("file list request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusGone {
		return nil, ErrTaskWorkspaceGone
	}
	if resp.StatusCode == http.StatusPreconditionFailed {
		return nil, ErrExecutorIncarnationChanged
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("file list returned status %d", resp.StatusCode)
	}
	var result FileListResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode file list response: %w", err)
	}
	return &result, nil
}

func signFilesRequest(httpReq *http.Request, workspaceID, taskID, bodySHA256 string) error {
	token, err := activationauth.SignFromEnv(
		activationauth.ScopeFiles,
		activationauth.Identity{
			WorkspaceID:  workspaceID,
			TaskID:       taskID,
			Generation:   0,
			FencingToken: 1,
		},
		bodySHA256,
		time.Now(),
	)
	if err != nil {
		return fmt.Errorf("create files authorization: %w", err)
	}
	httpReq.Header.Set("Authorization", "Bearer "+token)
	return nil
}

// DeleteTaskWorkspace deletes only the ephemeral workspace for one exact
// workspace/task identity. The executor never receives the manager's cleanup
// secret; it verifies a short-lived task-bound activation token instead.
func DeleteTaskWorkspace(ctx context.Context, baseURL, workspaceID, taskID string, timeout time.Duration) error {
	request, err := http.NewRequestWithContext(ctx, http.MethodDelete, strings.TrimRight(baseURL, "/")+"/workspace/task", nil)
	if err != nil {
		return fmt.Errorf("failed to create task workspace delete request: %w", err)
	}
	query := request.URL.Query()
	query.Set("workspace_id", workspaceID)
	query.Set("task_id", taskID)
	request.URL.RawQuery = query.Encode()
	token, err := activationauth.SignFromEnv(
		activationauth.ScopeCleanup,
		activationauth.Identity{
			WorkspaceID:  workspaceID,
			TaskID:       taskID,
			Generation:   0,
			FencingToken: 1,
		},
		activationauth.BodySHA256(nil),
		time.Now(),
	)
	if err != nil {
		return fmt.Errorf("create task workspace cleanup authorization: %w", err)
	}
	request.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{Timeout: timeout}
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("task workspace delete request failed: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusNoContent {
		return fmt.Errorf("task workspace delete returned status %d", response.StatusCode)
	}
	return nil
}

func GetRuntimeManifest(ctx context.Context, baseURL string, timeout time.Duration) (*runtimeinfo.Manifest, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(baseURL, "/")+"/runtime/manifest", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create runtime manifest request: %w", err)
	}
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
	return &manifest, nil
}

// GetExecutorIncarnation identifies one activation-service process. Docker
// development workspaces live only in that process's ephemeral filesystem, so
// a changed value invalidates every manager-side hydration record.
func GetExecutorIncarnation(ctx context.Context, baseURL string, timeout time.Duration) (string, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(baseURL, "/")+"/health", nil)
	if err != nil {
		return "", fmt.Errorf("failed to create executor health request: %w", err)
	}
	client := &http.Client{Timeout: timeout}
	response, err := client.Do(request)
	if err != nil {
		return "", fmt.Errorf("executor health request failed: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return "", fmt.Errorf("executor health returned status %d", response.StatusCode)
	}
	var health struct {
		Status      string `json:"status"`
		Incarnation string `json:"incarnation"`
	}
	decoder := json.NewDecoder(io.LimitReader(response.Body, 4097))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&health); err != nil {
		return "", fmt.Errorf("decode executor health: %w", err)
	}
	if _, err := uuid.Parse(health.Incarnation); err != nil {
		return "", fmt.Errorf("executor health returned invalid incarnation")
	}
	return health.Incarnation, nil
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
func (c *Client) FindOrAssignPodForTask(ctx context.Context, workspaceID, taskID string) (*corev1.Pod, error) {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return nil, err
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	selector := fmt.Sprintf("%s=%s", labelTaskBinding, taskBinding(workspaceID, taskID))
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: selector,
		Limit:         1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list pods for task %s: %w", taskID, err)
	}
	if len(pods.Items) > 0 {
		pod := &pods.Items[0]
		if err := verifyTaskPodIdentity(pod, workspaceID, taskID); err != nil {
			return nil, err
		}
		if pod.Labels[labelStatus] == statusIdle {
			pod, err = c.markTaskAssigned(ctx, pod, workspaceID, taskID, now, c.taskLeaseTTL)
			if err != nil {
				return nil, err
			}
			return c.waitForPodRunning(ctx, pod.Name, 120*time.Second)
		}
		if err := c.TouchTaskPod(ctx, pod, c.taskLeaseTTL); err != nil {
			return nil, err
		}
		return c.waitForPodRunning(ctx, pod.Name, 120*time.Second)
	}

	return c.createTaskPodFromTemplate(ctx, workspaceID, taskID, now, c.taskLeaseTTL)
}

// FindPodForTask returns an existing task pod without selecting or cloning a
// runtime profile. Writeback must target the same pod that executed the command;
// creating a replacement would lose its workspace changes.
func (c *Client) FindPodForTask(ctx context.Context, workspaceID, taskID string) (*corev1.Pod, error) {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return nil, err
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return nil, err
	}
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf("%s=%s", labelTaskBinding, taskBinding(workspaceID, taskID)),
		Limit:         2,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list pods for task %s: %w", taskID, err)
	}
	if len(pods.Items) == 0 {
		return nil, fmt.Errorf("%w: workspace %s task %s", ErrTaskPodNotFound, workspaceID, taskID)
	}
	if len(pods.Items) != 1 {
		return nil, fmt.Errorf("multiple pods claim workspace %s task %s", workspaceID, taskID)
	}
	pod := &pods.Items[0]
	if err := verifyTaskPodIdentity(pod, workspaceID, taskID); err != nil {
		return nil, err
	}
	if pod.Labels[labelStatus] == statusIdle {
		pod, err = c.markTaskAssigned(ctx, pod, workspaceID, taskID, time.Now().UTC(), c.taskLeaseTTL)
		if err != nil {
			return nil, err
		}
		return c.waitForPodRunning(ctx, pod.Name, 120*time.Second)
	}
	if err := c.TouchTaskPod(ctx, pod, c.taskLeaseTTL); err != nil {
		return nil, err
	}
	return c.waitForPodRunning(ctx, pod.Name, 120*time.Second)
}

// ErrTaskPodNotFound means the live task workspace has already been reclaimed.
// Inspection callers use it to distinguish expiration from infrastructure errors.
var ErrTaskPodNotFound = errors.New("no assigned sandbox pod found")

// ErrTaskPodBusy means retirement raced a live operation. Cleanup callers
// retry instead of deleting a workspace beneath a command or file stream.
var ErrTaskPodBusy = errors.New("sandbox pod has active operations")

func (c *Client) markTaskAssigned(ctx context.Context, pod *corev1.Pod, workspaceID, taskID string, now time.Time, leaseTTL time.Duration) (*corev1.Pod, error) {
	if pod.Labels == nil {
		pod.Labels = make(map[string]string)
	}
	if pod.Annotations == nil {
		pod.Annotations = make(map[string]string)
	}
	if _, ok := pod.Annotations[annotationTaskAssignedAt]; !ok {
		pod.Annotations[annotationTaskAssignedAt] = now.Format(time.RFC3339)
	}
	pod.Labels[labelTaskBinding] = taskBinding(workspaceID, taskID)
	pod.Labels[labelStatus] = statusAssigned
	pod.Annotations[annotationTaskLastUsedAt] = now.Format(time.RFC3339)
	pod.Annotations[annotationTaskLeaseUntil] = now.Add(leaseTTL).Format(time.RFC3339)
	pod.Annotations[annotationWorkspaceID] = workspaceID
	pod.Annotations[annotationTaskID] = taskID
	delete(pod.Annotations, annotationTaskIdleSince)
	delete(pod.Annotations, annotationTaskCleanupAt)

	updated, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to assign pod to task %s: %w", taskID, err)
	}
	return updated, nil
}

func (c *Client) createTaskPodFromTemplate(ctx context.Context, workspaceID, taskID string, now time.Time, leaseTTL time.Duration) (*corev1.Pod, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf("%s=warm-pool,%s=%s", labelComponent, labelStatus, statusWaiting),
		Limit:         1,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list warm pool pod templates: %w", err)
	}
	if len(pods.Items) == 0 {
		return nil, fmt.Errorf("no warm pool pod template available for task %s", taskID)
	}

	template := pods.Items[0]
	pod := taskPodFromTemplate(template, c.namespace, workspaceID, taskID, now, leaseTTL)

	created, err := c.client.CoreV1().Pods(c.namespace).Create(ctx, pod, metav1.CreateOptions{})
	if err != nil {
		if k8serrors.IsAlreadyExists(err) {
			existing, getErr := c.client.CoreV1().Pods(c.namespace).Get(ctx, pod.Name, metav1.GetOptions{})
			if getErr != nil {
				return nil, fmt.Errorf("get concurrently created task pod %s: %w", pod.Name, getErr)
			}
			if identityErr := verifyTaskPodIdentity(existing, workspaceID, taskID); identityErr != nil {
				return nil, identityErr
			}
			return c.waitForPodRunning(ctx, existing.Name, 120*time.Second)
		}
		return nil, fmt.Errorf("failed to create task sandbox pod for %s: %w", taskID, err)
	}
	return c.waitForPodRunning(ctx, created.Name, 120*time.Second)
}

func taskPodFromTemplate(template corev1.Pod, namespace, workspaceID, taskID string, now time.Time, leaseTTL time.Duration) *corev1.Pod {
	labels := maps.Clone(template.Labels)
	if labels == nil {
		labels = make(map[string]string)
	}
	labels[labelComponent] = "workflow-sandbox"
	labels[labelManagedBy] = "mcp-manager"
	labels[labelTaskBinding] = taskBinding(workspaceID, taskID)
	labels[labelStatus] = statusAssigned

	annotations := maps.Clone(template.Annotations)
	if annotations == nil {
		annotations = make(map[string]string)
	}
	annotations[annotationTaskAssignedAt] = now.Format(time.RFC3339)
	annotations[annotationTaskLastUsedAt] = now.Format(time.RFC3339)
	annotations[annotationTaskLeaseUntil] = now.Add(leaseTTL).Format(time.RFC3339)
	annotations[annotationWorkspaceID] = workspaceID
	annotations[annotationTaskID] = taskID

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:        taskPodName(workspaceID, taskID),
			Namespace:   namespace,
			Labels:      labels,
			Annotations: annotations,
		},
		Spec: *template.Spec.DeepCopy(),
	}
	automountServiceAccountToken := false
	pod.Spec.AutomountServiceAccountToken = &automountServiceAccountToken
	pod.Spec.NodeName = ""
	return pod
}

func taskBinding(workspaceID, taskID string) string {
	sum := sha256.Sum256([]byte(workspaceID + "\x00" + taskID))
	return hex.EncodeToString(sum[:])[:52]
}

func taskPodName(workspaceID, taskID string) string {
	return "task-" + taskBinding(workspaceID, taskID)[:40]
}

func verifyTaskPodIdentity(pod *corev1.Pod, workspaceID, taskID string) error {
	if pod == nil || pod.Labels[labelTaskBinding] != taskBinding(workspaceID, taskID) ||
		pod.Annotations[annotationWorkspaceID] != workspaceID || pod.Annotations[annotationTaskID] != taskID {
		return fmt.Errorf("sandbox pod identity does not match workspace %s task %s", workspaceID, taskID)
	}
	return nil
}

// DeletePodForTask deletes any pod labeled with the given task id.
// The DaemonSet/Deployment that manages the warm pool replenishes the
// deleted pod automatically; emptyDir state goes with the pod.
func (c *Client) DeletePodForTask(ctx context.Context, workspaceID, taskID string) error {
	return c.RetirePodForTask(ctx, workspaceID, taskID, 0)
}

// DeleteExactPod invalidates one unsafe runtime binding with a Kubernetes UID
// precondition. A replacement pod that happens to reuse the deterministic name
// can never be deleted by a delayed cleanup from the previous incarnation.
func (c *Client) DeleteExactPod(ctx context.Context, pod *corev1.Pod) error {
	if pod == nil || pod.Name == "" || pod.UID == "" {
		return fmt.Errorf("exact sandbox pod name and UID are required")
	}
	uid := pod.UID
	err := c.client.CoreV1().Pods(c.namespace).Delete(ctx, pod.Name, metav1.DeleteOptions{
		Preconditions: &metav1.Preconditions{UID: &uid},
	})
	if k8serrors.IsNotFound(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("delete exact unsafe sandbox pod %s/%s: %w", pod.Name, pod.UID, err)
	}
	return nil
}

// VerifyOrBindExecutorIncarnation fences task filesystem state to one
// activation-service process. A container restart keeps the Kubernetes Pod UID
// but loses emptyDir/process-owned execution state, so Pod UID alone is not a
// sufficient workspace identity.
func (c *Client) VerifyOrBindExecutorIncarnation(ctx context.Context, pod *corev1.Pod) (*corev1.Pod, string, error) {
	if pod == nil || pod.Name == "" || pod.UID == "" || pod.Status.PodIP == "" {
		return nil, "", fmt.Errorf("ready sandbox pod identity and IP are required")
	}
	incarnation, err := c.observeExecutorIncarnation(ctx, pod)
	if err != nil {
		if pod.Annotations[annotationHydrationIncarnation] != "" {
			cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
			cleanupErr := c.DeleteExactPod(cleanupCtx, pod)
			cancel()
			return nil, "", errors.Join(ErrExecutorIncarnationChanged, err, cleanupErr)
		}
		return nil, "", err
	}
	for attempts := 0; attempts < 5; attempts++ {
		current, getErr := c.client.CoreV1().Pods(c.namespace).Get(ctx, pod.Name, metav1.GetOptions{})
		if getErr != nil {
			return nil, "", fmt.Errorf("read sandbox pod executor binding: %w", getErr)
		}
		if current.UID != pod.UID {
			return nil, "", ErrExecutorIncarnationChanged
		}
		if current.Annotations == nil {
			current.Annotations = make(map[string]string)
		}
		bound := current.Annotations[annotationHydrationIncarnation]
		if bound != "" && bound != incarnation {
			cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
			cleanupErr := c.DeleteExactPod(cleanupCtx, current)
			cancel()
			return nil, "", errors.Join(ErrExecutorIncarnationChanged, cleanupErr)
		}
		if bound == incarnation {
			return current, incarnation, nil
		}
		current.Annotations[annotationHydrationIncarnation] = incarnation
		updated, updateErr := c.client.CoreV1().Pods(c.namespace).Update(ctx, current, metav1.UpdateOptions{})
		if k8serrors.IsConflict(updateErr) {
			continue
		}
		if updateErr != nil {
			return nil, "", fmt.Errorf("bind sandbox executor incarnation: %w", updateErr)
		}
		return updated, incarnation, nil
	}
	return nil, "", fmt.Errorf("bind sandbox executor incarnation after repeated conflicts")
}

// RetirePodForTask moves task pods to an idle state and schedules
// garbage collection. A zero or negative TTL keeps the previous immediate
// deletion behavior.
func (c *Client) RetirePodForTask(ctx context.Context, workspaceID, taskID string, idleTTL time.Duration) error {
	now := time.Now().UTC()
	selector := fmt.Sprintf("%s=%s", labelTaskBinding, taskBinding(workspaceID, taskID))
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: selector,
	})
	if err != nil {
		return fmt.Errorf("failed to list pods for task %s: %w", taskID, err)
	}
	for _, pod := range pods.Items {
		if err := verifyTaskPodIdentity(&pod, workspaceID, taskID); err != nil {
			return err
		}
		operations, err := taskOperations(&pod, now)
		if err != nil {
			return err
		}
		if len(operations) > 0 || hydrationClaimActive(&pod, now) {
			return fmt.Errorf("%w for task %s", ErrTaskPodBusy, taskID)
		}
		if idleTTL <= 0 {
			uid := pod.UID
			resourceVersion := pod.ResourceVersion
			if err := c.client.CoreV1().Pods(c.namespace).Delete(ctx, pod.Name, metav1.DeleteOptions{
				Preconditions: &metav1.Preconditions{UID: &uid, ResourceVersion: &resourceVersion},
			}); err != nil {
				return fmt.Errorf("failed to delete pod %s for task %s: %w", pod.Name, taskID, err)
			}
			continue
		}
		if pod.Labels == nil {
			pod.Labels = make(map[string]string)
		}
		if pod.Annotations == nil {
			pod.Annotations = make(map[string]string)
		}
		pod.Labels[labelStatus] = statusIdle
		pod.Annotations[annotationTaskIdleSince] = now.Format(time.RFC3339)
		pod.Annotations[annotationTaskCleanupAt] = now.Add(idleTTL).Format(time.RFC3339)
		if err := setTaskOperations(&pod, operations); err != nil {
			return err
		}
		delete(pod.Annotations, annotationTaskLeaseUntil)
		if _, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, &pod, metav1.UpdateOptions{}); err != nil {
			return fmt.Errorf("failed to mark pod %s idle for task %s: %w", pod.Name, taskID, err)
		}
	}
	return nil
}

// BeginTaskOperation registers a renewable, uniquely-owned operation lease.
// Retirement and GC check the same annotation through optimistic concurrency.
func (c *Client) BeginTaskOperation(ctx context.Context, pod *corev1.Pod, leaseTTL time.Duration) (*TaskOperation, error) {
	if pod == nil || leaseTTL <= 0 {
		return nil, fmt.Errorf("task operation requires a pod and positive lease TTL")
	}
	token := uuid.NewString()
	for attempts := 0; attempts < 5; attempts++ {
		current, err := c.client.CoreV1().Pods(c.namespace).Get(ctx, pod.Name, metav1.GetOptions{})
		if err != nil {
			return nil, fmt.Errorf("read task pod before operation: %w", err)
		}
		if pod.UID != "" && current.UID != pod.UID {
			return nil, fmt.Errorf("task pod %s identity changed before operation", pod.Name)
		}
		binding := pod.Labels[labelTaskBinding]
		if binding == "" || current.Labels[labelTaskBinding] != binding {
			return nil, fmt.Errorf("task pod %s binding changed before operation", pod.Name)
		}
		now := time.Now().UTC()
		operations, err := taskOperations(current, now)
		if err != nil {
			return nil, err
		}
		operations[token] = now.Add(leaseTTL).Format(time.RFC3339Nano)
		if current.Annotations == nil {
			current.Annotations = make(map[string]string)
		}
		if current.Labels == nil {
			current.Labels = make(map[string]string)
		}
		executorIncarnation := current.Annotations[annotationHydrationIncarnation]
		if executorIncarnation == "" {
			return nil, fmt.Errorf("task pod %s has no executor incarnation binding", pod.Name)
		}
		current.Labels[labelStatus] = statusAssigned
		current.Annotations[annotationTaskLastUsedAt] = now.Format(time.RFC3339)
		current.Annotations[annotationTaskLeaseUntil] = now.Add(leaseTTL).Format(time.RFC3339)
		delete(current.Annotations, annotationTaskIdleSince)
		delete(current.Annotations, annotationTaskCleanupAt)
		if err := setTaskOperations(current, operations); err != nil {
			return nil, err
		}
		updated, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, current, metav1.UpdateOptions{})
		if k8serrors.IsConflict(err) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("register task operation: %w", err)
		}
		return &TaskOperation{
			PodName: updated.Name, PodUID: string(updated.UID), Binding: binding, Token: token,
			ExecutorIncarnation: executorIncarnation,
		}, nil
	}
	return nil, fmt.Errorf("register task operation after repeated conflicts")
}

// TaskPodForOperation resolves only the exact pod UID protected by a live
// distributed operation lease and verifies that its committed hydration
// revision is still the one selected for this demand.
func (c *Client) TaskPodForOperation(ctx context.Context, operation *TaskOperation, hydrationRevision string) (*corev1.Pod, error) {
	if operation == nil || operation.PodName == "" || operation.PodUID == "" || operation.Binding == "" || operation.Token == "" || operation.ExecutorIncarnation == "" {
		return nil, fmt.Errorf("task operation identity is required")
	}
	pod, err := c.client.CoreV1().Pods(c.namespace).Get(ctx, operation.PodName, metav1.GetOptions{})
	if err != nil {
		return nil, fmt.Errorf("read bound task pod: %w", err)
	}
	if string(pod.UID) != operation.PodUID || pod.Labels[labelTaskBinding] != operation.Binding {
		return nil, fmt.Errorf("task pod binding changed during composite operation")
	}
	operations, err := taskOperations(pod, time.Now().UTC())
	if err != nil {
		return nil, err
	}
	if _, ok := operations[operation.Token]; !ok {
		return nil, fmt.Errorf("task operation lease ownership was lost")
	}
	if hydrationRevision == "" || pod.Annotations[annotationHydrationRev] != hydrationRevision {
		return nil, fmt.Errorf("task pod hydration binding changed during composite operation")
	}
	if pod.Annotations[annotationHydrationIncarnation] != operation.ExecutorIncarnation {
		return nil, ErrExecutorIncarnationChanged
	}
	if pod.DeletionTimestamp != nil || pod.Status.Phase != corev1.PodRunning || pod.Status.PodIP == "" || !podConditionTrue(pod.Status.Conditions, corev1.PodReady) {
		return nil, fmt.Errorf("bound task pod is not ready")
	}
	observed, err := c.observeExecutorIncarnation(ctx, pod)
	if err != nil {
		return nil, err
	}
	if observed != operation.ExecutorIncarnation {
		return nil, ErrExecutorIncarnationChanged
	}
	return pod, nil
}

func (c *Client) TouchTaskOperation(ctx context.Context, operation *TaskOperation, leaseTTL time.Duration) error {
	return c.updateTaskOperation(ctx, operation, leaseTTL, false)
}

func (c *Client) EndTaskOperation(ctx context.Context, operation *TaskOperation) error {
	return c.updateTaskOperation(ctx, operation, 0, true)
}

func (c *Client) updateTaskOperation(ctx context.Context, operation *TaskOperation, leaseTTL time.Duration, remove bool) error {
	if operation == nil || operation.PodName == "" || operation.Binding == "" || operation.Token == "" {
		return fmt.Errorf("task operation identity is required")
	}
	for attempts := 0; attempts < 5; attempts++ {
		pod, err := c.client.CoreV1().Pods(c.namespace).Get(ctx, operation.PodName, metav1.GetOptions{})
		if err != nil {
			return fmt.Errorf("read task pod operation: %w", err)
		}
		if operation.PodUID != "" && string(pod.UID) != operation.PodUID {
			return fmt.Errorf("task pod %s identity changed during operation", operation.PodName)
		}
		if pod.Labels[labelTaskBinding] != operation.Binding {
			return fmt.Errorf("task pod %s binding changed during operation", operation.PodName)
		}
		now := time.Now().UTC()
		operations, err := taskOperations(pod, now)
		if err != nil {
			return err
		}
		if _, ok := operations[operation.Token]; !ok {
			return fmt.Errorf("task operation lease ownership was lost")
		}
		if remove {
			delete(operations, operation.Token)
		} else {
			if leaseTTL <= 0 {
				return fmt.Errorf("task operation renewal TTL must be positive")
			}
			operations[operation.Token] = now.Add(leaseTTL).Format(time.RFC3339Nano)
			pod.Annotations[annotationTaskLastUsedAt] = now.Format(time.RFC3339)
			pod.Annotations[annotationTaskLeaseUntil] = now.Add(leaseTTL).Format(time.RFC3339)
		}
		if err := setTaskOperations(pod, operations); err != nil {
			return err
		}
		if _, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{}); k8serrors.IsConflict(err) {
			continue
		} else if err != nil {
			return fmt.Errorf("update task operation: %w", err)
		}
		return nil
	}
	return fmt.Errorf("update task operation after repeated conflicts")
}

func taskOperations(pod *corev1.Pod, now time.Time) (map[string]string, error) {
	operations := make(map[string]string)
	if pod == nil || pod.Annotations == nil || pod.Annotations[annotationTaskOperations] == "" {
		return operations, nil
	}
	if err := json.Unmarshal([]byte(pod.Annotations[annotationTaskOperations]), &operations); err != nil {
		return nil, fmt.Errorf("decode task operations for pod %s: %w", pod.Name, err)
	}
	for token, deadlineRaw := range operations {
		deadline, err := time.Parse(time.RFC3339Nano, deadlineRaw)
		if err != nil {
			return nil, fmt.Errorf("invalid task operation deadline for pod %s", pod.Name)
		}
		if !now.Before(deadline) {
			delete(operations, token)
		}
	}
	return operations, nil
}

func setTaskOperations(pod *corev1.Pod, operations map[string]string) error {
	if pod.Annotations == nil {
		pod.Annotations = make(map[string]string)
	}
	if len(operations) == 0 {
		delete(pod.Annotations, annotationTaskOperations)
		return nil
	}
	encoded, err := json.Marshal(operations)
	if err != nil {
		return fmt.Errorf("encode task operations: %w", err)
	}
	pod.Annotations[annotationTaskOperations] = string(encoded)
	return nil
}

func hydrationClaimActive(pod *corev1.Pod, now time.Time) bool {
	if pod == nil || pod.Annotations == nil || pod.Annotations[annotationHydrationClaim] == "" {
		return false
	}
	deadline, err := time.Parse(time.RFC3339Nano, pod.Annotations[annotationHydrationUntil])
	return err != nil || now.Before(deadline)
}

// TouchTaskPod extends the active lease for a task pod. The GC loop
// only deletes assigned pods after this lease expires, which prevents orphaned
// pods from living forever while leaving long-running tasks alone.
func (c *Client) TouchTaskPod(ctx context.Context, pod *corev1.Pod, leaseTTL time.Duration) error {
	if pod == nil || pod.Labels[labelTaskBinding] == "" || leaseTTL <= 0 {
		return nil
	}
	current, err := c.client.CoreV1().Pods(c.namespace).Get(ctx, pod.Name, metav1.GetOptions{})
	if err != nil {
		return fmt.Errorf("refresh task pod %s before lease extension: %w", pod.Name, err)
	}
	if pod.UID != "" && current.UID != pod.UID {
		return fmt.Errorf("task pod %s identity changed before lease extension", pod.Name)
	}
	if current.Labels[labelTaskBinding] != pod.Labels[labelTaskBinding] {
		return fmt.Errorf("task pod %s binding changed before lease extension", pod.Name)
	}
	if current.Annotations == nil {
		current.Annotations = make(map[string]string)
	}
	now := time.Now().UTC()
	current.Annotations[annotationTaskLastUsedAt] = now.Format(time.RFC3339)
	current.Annotations[annotationTaskLeaseUntil] = now.Add(leaseTTL).Format(time.RFC3339)
	if _, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, current, metav1.UpdateOptions{}); err != nil {
		return fmt.Errorf("failed to extend task lease for pod %s: %w", pod.Name, err)
	}
	return nil
}

// EnsurePodHydrated serializes immutable input materialization in Kubernetes
// control-plane state. The claim is fenced by an opaque token and renewed while
// hydration runs; no agent-writable file is trusted as a completion marker.
func (c *Client) EnsurePodHydrated(
	ctx context.Context,
	workspaceID, taskID, revision string,
	hydrate func(context.Context) error,
) error {
	_, err := c.EnsurePodHydratedBinding(
		ctx, workspaceID, taskID, revision, hydrate,
	)
	return err
}

// EnsurePodHydratedBinding returns the exact pod whose control-plane hydration
// revision was committed. Callers can register a distributed task-operation
// lease against this UID before executing, so a replacement pod can never be
// mistaken for the one that received the inputs.
func (c *Client) EnsurePodHydratedBinding(
	ctx context.Context,
	workspaceID, taskID, revision string,
	hydrate func(context.Context) error,
) (*corev1.Pod, error) {
	if hydrate == nil || len(revision) != sha256.Size*2 {
		return nil, fmt.Errorf("workspace hydration requires a callback and sha256 revision")
	}
	if _, err := hex.DecodeString(revision); err != nil {
		return nil, fmt.Errorf("workspace hydration revision is invalid")
	}
	assigned, err := c.FindOrAssignPodForTask(ctx, workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	_, executorIncarnation, err := c.VerifyOrBindExecutorIncarnation(ctx, assigned)
	if err != nil {
		return nil, err
	}
	claim := uuid.NewString()
	const claimTTL = 30 * time.Second
	for {
		pod, err := c.findTaskPodWithoutTouch(ctx, workspaceID, taskID)
		if err != nil {
			return nil, err
		}
		currentRevision := pod.Annotations[annotationHydrationRev]
		if currentRevision == revision {
			return pod, nil
		}
		if currentRevision != "" {
			return nil, fmt.Errorf("live sandbox is hydrated from revision %s and cannot be mutated to %s", currentRevision, revision)
		}
		claimUntil, _ := time.Parse(time.RFC3339Nano, pod.Annotations[annotationHydrationUntil])
		if pod.Annotations[annotationHydrationClaim] != "" && time.Now().UTC().Before(claimUntil) {
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(50 * time.Millisecond):
				continue
			}
		}
		pod.Annotations[annotationHydrationClaim] = claim
		pod.Annotations[annotationHydrationUntil] = time.Now().UTC().Add(claimTTL).Format(time.RFC3339Nano)
		pod.Annotations[annotationHydrationClaimIncarnation] = executorIncarnation
		if _, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{}); err != nil {
			if k8serrors.IsConflict(err) {
				continue
			}
			return nil, fmt.Errorf("claim workspace hydration for pod %s: %w", pod.Name, err)
		}
		break
	}

	hydrationCtx, cancel := context.WithCancel(ctx)
	stopHeartbeat := make(chan struct{})
	heartbeatDone := make(chan error, 1)
	go c.renewHydrationClaim(hydrationCtx, workspaceID, taskID, claim, executorIncarnation, claimTTL, stopHeartbeat, heartbeatDone)
	hydrateErr := hydrate(hydrationCtx)
	close(stopHeartbeat)
	heartbeatErr := <-heartbeatDone
	cancel()
	if hydrateErr != nil || heartbeatErr != nil {
		_, _ = c.finishHydrationClaim(context.Background(), workspaceID, taskID, claim, "", executorIncarnation)
		if heartbeatErr != nil {
			return nil, heartbeatErr
		}
		return nil, hydrateErr
	}
	return c.finishHydrationClaim(ctx, workspaceID, taskID, claim, revision, executorIncarnation)
}

func (c *Client) renewHydrationClaim(
	ctx context.Context,
	workspaceID, taskID, claim, executorIncarnation string,
	ttl time.Duration,
	stop <-chan struct{},
	done chan<- error,
) {
	interval := ttl / 3
	if leaseInterval := c.taskLeaseTTL / 3; leaseInterval < interval {
		interval = leaseInterval
	}
	if interval <= 0 {
		interval = time.Nanosecond
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-stop:
			done <- nil
			return
		case <-ctx.Done():
			done <- ctx.Err()
			return
		case <-ticker.C:
			pod, err := c.findTaskPodWithoutTouch(ctx, workspaceID, taskID)
			if err != nil {
				done <- err
				return
			}
			if pod.Annotations[annotationHydrationClaim] != claim {
				done <- fmt.Errorf("workspace hydration claim ownership was lost")
				return
			}
			if pod.Annotations[annotationHydrationClaimIncarnation] != executorIncarnation || pod.Annotations[annotationHydrationIncarnation] != executorIncarnation {
				done <- ErrExecutorIncarnationChanged
				return
			}
			now := time.Now().UTC()
			pod.Annotations[annotationHydrationUntil] = now.Add(ttl).Format(time.RFC3339Nano)
			pod.Annotations[annotationTaskLastUsedAt] = now.Format(time.RFC3339)
			pod.Annotations[annotationTaskLeaseUntil] = now.Add(c.taskLeaseTTL).Format(time.RFC3339)
			if _, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{}); err != nil {
				done <- fmt.Errorf("renew workspace hydration claim: %w", err)
				return
			}
		}
	}
}

func (c *Client) finishHydrationClaim(ctx context.Context, workspaceID, taskID, claim, revision, executorIncarnation string) (*corev1.Pod, error) {
	for attempts := 0; attempts < 5; attempts++ {
		pod, err := c.findTaskPodWithoutTouch(ctx, workspaceID, taskID)
		if err != nil {
			return nil, err
		}
		if pod.Annotations[annotationHydrationClaim] != claim {
			return nil, fmt.Errorf("workspace hydration claim ownership was lost before commit")
		}
		if revision != "" {
			if pod.Annotations[annotationHydrationClaimIncarnation] != executorIncarnation || pod.Annotations[annotationHydrationIncarnation] != executorIncarnation {
				return nil, ErrExecutorIncarnationChanged
			}
			observed, observeErr := c.observeExecutorIncarnation(ctx, pod)
			if observeErr != nil || observed != executorIncarnation {
				cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
				cleanupErr := c.DeleteExactPod(cleanupCtx, pod)
				cancel()
				return nil, errors.Join(ErrExecutorIncarnationChanged, observeErr, cleanupErr)
			}
			pod.Annotations[annotationHydrationRev] = revision
		}
		delete(pod.Annotations, annotationHydrationClaim)
		delete(pod.Annotations, annotationHydrationUntil)
		delete(pod.Annotations, annotationHydrationClaimIncarnation)
		updated, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
		if err != nil {
			if k8serrors.IsConflict(err) {
				continue
			}
			return nil, fmt.Errorf("commit workspace hydration state: %w", err)
		}
		return updated, nil
	}
	return nil, fmt.Errorf("commit workspace hydration state after repeated conflicts")
}

func (c *Client) findTaskPodWithoutTouch(ctx context.Context, workspaceID, taskID string) (*corev1.Pod, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: fmt.Sprintf("%s=%s", labelTaskBinding, taskBinding(workspaceID, taskID)),
		Limit:         2,
	})
	if err != nil {
		return nil, fmt.Errorf("list pod for workspace hydration: %w", err)
	}
	if len(pods.Items) != 1 {
		return nil, fmt.Errorf("%w: expected one pod for workspace %s task %s", ErrTaskPodNotFound, workspaceID, taskID)
	}
	pod := &pods.Items[0]
	if err := verifyTaskPodIdentity(pod, workspaceID, taskID); err != nil {
		return nil, err
	}
	return pod, nil
}

// DeleteExpiredTaskPods removes idle task sandboxes after their cleanup
// deadline and assigned sandboxes after their orphan lease expires.
func (c *Client) DeleteExpiredTaskPods(ctx context.Context, now time.Time) (int, error) {
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: labelTaskBinding,
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
		operations, err := taskOperations(&pod, now)
		if err != nil {
			return deleted, err
		}
		if len(operations) > 0 || hydrationClaimActive(&pod, now) {
			continue
		}
		deadline, err := time.Parse(time.RFC3339, deadlineRaw)
		if err != nil || now.Before(deadline) {
			continue
		}
		uid := pod.UID
		resourceVersion := pod.ResourceVersion
		if err := c.client.CoreV1().Pods(c.namespace).Delete(ctx, pod.Name, metav1.DeleteOptions{
			Preconditions: &metav1.Preconditions{UID: &uid, ResourceVersion: &resourceVersion},
		}); err != nil {
			if k8serrors.IsNotFound(err) || k8serrors.IsConflict(err) {
				continue
			}
			return deleted, fmt.Errorf("failed to delete expired task sandbox pod %s: %w", pod.Name, err)
		}
		deleted++
	}
	return deleted, nil
}

// ListTaskPodsForWorkspace returns live Kubernetes data-plane state, not
// manager-local cache entries. Every matching record is identity-checked before
// it crosses the workspace-scoped API boundary.
func (c *Client) ListTaskPodsForWorkspace(ctx context.Context, workspaceID string) ([]TaskPodInfo, error) {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return nil, err
	}
	pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: labelTaskBinding,
	})
	if err != nil {
		return nil, fmt.Errorf("list task sandbox pods: %w", err)
	}
	result := make([]TaskPodInfo, 0, len(pods.Items))
	for i := range pods.Items {
		pod := &pods.Items[i]
		if pod.Annotations[annotationWorkspaceID] != workspaceID {
			continue
		}
		taskID := pod.Annotations[annotationTaskID]
		if err := verifyTaskPodIdentity(pod, workspaceID, taskID); err != nil {
			return nil, err
		}
		state := pod.Labels[labelStatus]
		if state != statusAssigned && state != statusIdle {
			return nil, fmt.Errorf("task pod %s has invalid lifecycle state %q", pod.Name, state)
		}
		if pod.Spec.RuntimeClassName == nil || *pod.Spec.RuntimeClassName == "" {
			return nil, fmt.Errorf("task pod %s has no runtime isolation class", pod.Name)
		}
		var expiresAt *time.Time
		expiryRaw := pod.Annotations[annotationTaskLeaseUntil]
		if state == statusIdle {
			expiryRaw = pod.Annotations[annotationTaskCleanupAt]
		}
		if expiryRaw != "" {
			parsed, err := time.Parse(time.RFC3339, expiryRaw)
			if err != nil {
				return nil, fmt.Errorf("task pod %s has invalid expiry", pod.Name)
			}
			expiresAt = &parsed
		}
		resources := map[string]string{}
		if len(pod.Spec.Containers) > 0 {
			container := pod.Spec.Containers[0]
			if cpu := container.Resources.Limits.Cpu(); cpu != nil && !cpu.IsZero() {
				resources["cpu"] = cpu.String()
			}
			if memory := container.Resources.Limits.Memory(); memory != nil && !memory.IsZero() {
				resources["memory"] = memory.String()
			}
		}
		result = append(result, TaskPodInfo{
			ID: string(pod.UID), WorkspaceID: workspaceID, TaskID: taskID,
			State:     state,
			CreatedAt: pod.CreationTimestamp.Time, ExpiresAt: expiresAt,
			Resources: resources, Isolation: *pod.Spec.RuntimeClassName,
		})
	}
	return result, nil
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
			"%s=warm-pool,%s=%s",
			labelComponent,
			labelStatus,
			statusWaiting,
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

// waitForPodRunning polls until the named pod is addressable and Kubernetes has
// observed every readiness probe as healthy.
func (c *Client) waitForPodRunning(ctx context.Context, podName string, timeout time.Duration) (*corev1.Pod, error) {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		pod, err := c.client.CoreV1().Pods(c.namespace).Get(ctx, podName, metav1.GetOptions{})
		if err != nil {
			return nil, fmt.Errorf("failed to get pod %s: %w", podName, err)
		}
		if pod.Status.Phase == corev1.PodRunning && pod.Status.PodIP != "" && podConditionTrue(pod.Status.Conditions, corev1.PodReady) {
			return pod, nil
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
	return nil, fmt.Errorf("timed out waiting for pod %s to become Ready", podName)
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
