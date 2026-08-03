// Activation service runs inside warm pods
// Handles on-demand MCP activation via HTTP API
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"math"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/execsupervisor"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/workspace"
	"github.com/google/uuid"
)

var (
	status     = "waiting"
	mcpProcess *os.Process
	logger     *slog.Logger

	// lastRequestTime tracks the wall-clock time of the most recent /execute
	// or /activate call. The idle-timeout watchdog reads this to decide when
	// to self-exit, which lets K8s reclaim the pod if mcp-manager never
	// issues an explicit DELETE (worker crash, network partition, etc.). Active
	// requests are tracked separately so a long-running command is never killed
	// just because it has been quiet for longer than the idle TTL.
	lastRequestMu  sync.Mutex
	lastRequest    = time.Now()
	activeRequests int
	servicePolicy  activationPolicy
	// serviceIncarnation changes on every executor process start. The manager
	// uses it to invalidate hydration records backed by this process's ephemeral
	// filesystem instead of assuming a restarted executor still has the files.
	serviceIncarnation = uuid.NewString()
)

// Mutating operations for one task workspace are serialized. This makes the
// live file-count check authoritative even when shell and file requests arrive
// concurrently; fixed stripes avoid an unbounded lock registry.
var workspaceMutationStripes [256]sync.Mutex

func lockWorkspaceMutation(workspaceID, taskID string) func() {
	digest := sha256.Sum256([]byte(workspaceID + "\x00" + taskID))
	lock := &workspaceMutationStripes[int(digest[0])]
	lock.Lock()
	return lock.Unlock
}

type activationPolicy struct {
	MaxExecutionTimeoutSeconds int
	IdleTimeout                time.Duration
	WorkspaceLimits            sandboxruntime.WorkspaceLimits
}

const maxActivationRequestBytes = 64 * 1024 * 1024

// workspaceRoot is the parent directory for hydrated task workspaces.
// In K8s pods this is mounted as an emptyDir so it dies with the pod;
// in compose it's a plain directory inside the container with the same
// effect (container removed → directory gone). Overridable via
// WORKSPACE_ROOT for tests and local dev outside containers.
var workspaceRoot = func() string {
	if v := os.Getenv("WORKSPACE_ROOT"); v != "" {
		return v
	}
	return "/workspace"
}()

// ActivateRequest represents the activation request.
// The executable is always taken from the image's own ENTRYPOINT (verified by
// MCPImageHash) — there is intentionally no entrypoint override field.
// Command may override the image's CMD to pass different arguments.
type ActivateRequest struct {
	MCPImage     string            `json:"mcp_image"`
	MCPImageHash string            `json:"mcp_image_hash"`
	Port         int               `json:"port"`
	Command      []string          `json:"command"`
	Env          map[string]string `json:"env"`
	HealthCheck  *HealthCheck      `json:"health_check,omitempty"`
}

// HealthCheck represents health check configuration
type HealthCheck struct {
	Path string `json:"path,omitempty"`
	Port int    `json:"port,omitempty"`
}

// ActivateResponse represents the activation response
type ActivateResponse struct {
	Status           string `json:"status"`
	MCPPort          int    `json:"mcp_port"`
	ActivationTimeMs int    `json:"activation_time_ms"`
}

// ErrorResponse represents an error response
type ErrorResponse struct {
	Error string `json:"error"`
}

func main() {
	logger = slog.New(slog.NewJSONHandler(os.Stdout, nil))
	logger.Info("Activation service starting", "status", status)
	policy, err := loadActivationPolicy()
	if err != nil {
		logger.Error("Activation service policy is invalid", "error", err)
		os.Exit(1)
	}
	servicePolicy = policy

	http.HandleFunc("/health", healthHandler)
	http.HandleFunc("/activate", activateHandler)
	http.HandleFunc("/execute", executeHandler)
	http.HandleFunc("/files", filesHandler)
	http.HandleFunc("/files/content", fileContentHandler)
	http.HandleFunc("/workspace/task", workspaceTaskHandler)
	http.HandleFunc("/workspace/writeback", workspaceWritebackHandler)
	http.HandleFunc("/runtime/manifest", runtimeManifestHandler)

	port := os.Getenv("ACTIVATION_PORT")
	if port == "" {
		port = "8080"
	}

	startIdleWatchdog(policy.IdleTimeout)

	// Security: Configure server with timeouts to prevent Slowloris attacks
	server := &http.Server{
		Addr:              ":" + port,
		Handler:           nil,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       10 * time.Minute,
		WriteTimeout:      time.Duration(policy.MaxExecutionTimeoutSeconds)*time.Second + execsupervisor.TransportGrace,
		IdleTimeout:       120 * time.Second,
	}

	logger.Info("Listening", "port", port)
	if err := server.ListenAndServe(); err != nil {
		logger.Error("Server failed", "error", err)
		os.Exit(1)
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	response := map[string]string{
		"status":      status,
		"incarnation": serviceIncarnation,
	}
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(response); err != nil {
		logger.Error("Failed to encode response", "error", err)
	}
}

func requireExecutorIncarnation(w http.ResponseWriter, expected string) bool {
	if expected == "" {
		return true
	}
	if _, err := uuid.Parse(expected); err != nil {
		http.Error(w, `{"error": "executor_incarnation is invalid"}`, http.StatusBadRequest)
		return false
	}
	if expected != serviceIncarnation {
		http.Error(w, `{"error": "executor_incarnation_changed"}`, http.StatusPreconditionFailed)
		return false
	}
	return true
}

func activateHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}
	beginRequest()
	defer endRequest()

	start := time.Now()

	if status != "waiting" {
		http.Error(w, `{"error": "pod already assigned"}`, http.StatusConflict)
		return
	}

	body, err := readActivationRequestBody(r)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid request: %v"}`, err), http.StatusBadRequest)
		return
	}
	var req ActivateRequest
	if err := json.NewDecoder(bytes.NewReader(body)).Decode(&req); err != nil {
		logger.Error("Failed to decode request", "error", err)
		http.Error(w, fmt.Sprintf(`{"error": "invalid request: %v"}`, err), http.StatusBadRequest)
		return
	}
	logger.Info("Request decoded", "image", req.MCPImage, "port", req.Port, "command", req.Command)

	// Validate required fields
	if req.MCPImage == "" {
		http.Error(w, `{"error": "mcp_image is required"}`, http.StatusBadRequest)
		return
	}
	if req.MCPImageHash == "" {
		http.Error(w, `{"error": "mcp_image_hash is required"}`, http.StatusBadRequest)
		return
	}
	if err := ValidatePort(req.Port); err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusBadRequest)
		return
	}

	// Security: Validate image name
	if err := ValidateImageName(req.MCPImage); err != nil {
		logger.Error("Image validation failed", "error", err, "image", req.MCPImage)
		http.Error(w, fmt.Sprintf(`{"error": "invalid image name: %s"}`, err.Error()), http.StatusBadRequest)
		return
	}

	// Security: Validate image hash
	if err := ValidateHash(req.MCPImageHash); err != nil {
		logger.Error("Hash validation failed", "error", err)
		http.Error(w, fmt.Sprintf(`{"error": "invalid image hash: %s"}`, err.Error()), http.StatusBadRequest)
		return
	}
	if !authorizeActivationRequest(w, r, activationauth.ScopeActivate, activationauth.Identity{
		WorkspaceID: "mcp-control", TaskID: req.MCPImageHash, Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(body)) {
		return
	}

	// Validate command override arguments (shell metacharacter check).
	if len(req.Command) > 0 {
		if err := ValidateCommandArgs(req.Command); err != nil {
			logger.Error("Command validation failed", "error", err)
			http.Error(w, fmt.Sprintf(`{"error": "invalid command: %s"}`, err.Error()), http.StatusBadRequest)
			return
		}
	}

	logger.Info("Activation requested",
		"image", req.MCPImage,
		"hash", req.MCPImageHash,
		"port", req.Port,
	)

	status = "activating"

	if err := activate(req); err != nil {
		status = "waiting"
		logger.Error("Activation failed", "error", err)
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusInternalServerError)
		return
	}

	status = "ready"
	elapsed := time.Since(start).Milliseconds()

	logger.Info("Activation complete",
		"status", status,
		"elapsed_ms", elapsed,
	)

	response := ActivateResponse{
		Status:           "ready",
		MCPPort:          req.Port,
		ActivationTimeMs: int(elapsed),
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(response); err != nil {
		logger.Error("Failed to encode response", "error", err)
	}
}

func activate(req ActivateRequest) error {
	extractDir := "/app/mcp-overlay"

	// Step 1: Download/extract MCP image
	if err := prepareMCP(req.MCPImage, req.MCPImageHash, extractDir); err != nil {
		return fmt.Errorf("failed to prepare MCP: %w", err)
	}

	// Step 2: Parse image config — the executable is taken from here, not from the request.
	// The image was verified by hash in step 1, so its config is trusted content.
	imageConfig, err := ParseImageConfig(extractDir)
	if err != nil {
		return fmt.Errorf("failed to parse image config (image must define ENTRYPOINT or CMD): %w", err)
	}

	// req.Command may override CMD args; req.Entrypoint is intentionally ignored —
	// the executable always comes from the hash-verified image config.
	entrypoint, command, err := GetEffectiveCommand(imageConfig, req.Command)
	if err != nil {
		return err
	}

	logger.Info("Resolved command",
		"entrypoint", entrypoint,
		"command", command,
	)

	// Step 3: Build environment
	env := buildEnvironment(imageConfig, req.Env, req.Port, req.MCPImageHash)

	// Step 4: Start MCP process
	if err := startContainer(extractDir, imageConfig.WorkingDir, entrypoint, command, env); err != nil {
		return fmt.Errorf("failed to start container: %w", err)
	}

	// Step 5: Wait for ready
	healthPort := req.Port
	if req.HealthCheck != nil && req.HealthCheck.Port > 0 {
		healthPort = req.HealthCheck.Port
	}
	healthPath := ""
	if req.HealthCheck != nil {
		healthPath = req.HealthCheck.Path
	}

	// Security: Validate health check path to prevent SSRF
	if err := ValidateHealthCheckPath(healthPath); err != nil {
		return fmt.Errorf("invalid health check path: %w", err)
	}

	if err := waitForReady(30*time.Second, healthPort, healthPath); err != nil {
		if mcpProcess != nil {
			if killErr := mcpProcess.Kill(); killErr != nil {
				logger.Error("Failed to kill process", "error", killErr)
			}
		}
		return fmt.Errorf("container failed to become ready: %w", err)
	}

	return nil
}

func prepareMCP(image, hash, extractDir string) error {
	cacheDir := "/var/cache/mcp-images"

	// Ensure directories exist
	if err := os.MkdirAll(cacheDir, 0750); err != nil {
		return err
	}
	if err := os.MkdirAll(extractDir, 0750); err != nil {
		return err
	}

	// Security: Validate the hash format and construct safe path
	if err := ValidateHash(hash); err != nil {
		return err
	}

	imagePath := filepath.Join(cacheDir, hash+".tar")

	// Security: Validate the constructed path doesn't escape cacheDir
	if err := ValidateFilePath(cacheDir, imagePath); err != nil {
		return err
	}

	// Check if already cached
	if _, err := os.Stat(imagePath); os.IsNotExist(err) {
		logger.Info("Downloading MCP image", "image", image)

		// Security: Use safe command building
		cmd, err := BuildSkopeoCommand(image, imagePath)
		if err != nil {
			return err
		}
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr

		if err := cmd.Run(); err != nil {
			return fmt.Errorf("skopeo failed: %w", err)
		}
	} else {
		logger.Info("Using cached MCP image", "path", imagePath)
	}

	// Extract image
	logger.Info("Extracting MCP image")
	if err := extractImage(imagePath, extractDir); err != nil {
		return fmt.Errorf("failed to extract: %w", err)
	}
	if err := installRuntimeNetworkConfig(extractDir); err != nil {
		return fmt.Errorf("failed to install runtime network config: %w", err)
	}

	return nil
}

func extractImage(imagePath, extractDir string) error {
	// Clean extract directory
	if err := os.RemoveAll(extractDir); err != nil {
		return err
	}
	if err := os.MkdirAll(extractDir, 0750); err != nil {
		return err
	}

	// Create temp directory for extraction
	tempDir, err := os.MkdirTemp("", "mcp-extract-*")
	if err != nil {
		return err
	}
	defer os.RemoveAll(tempDir)

	// Security: Validate tempDir is safe
	if err := ValidateFilePath(os.TempDir(), tempDir); err != nil {
		return err
	}

	// Extract docker archive tar
	cmd, err := SafeCommand("tar", "-xf", imagePath, "-C", tempDir)
	if err != nil {
		return err
	}
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("failed to extract archive: %w", err)
	}

	// Parse manifest.json to get layer order and config file
	manifestPath := filepath.Join(tempDir, "manifest.json")
	manifestData, err := os.ReadFile(manifestPath)
	if err != nil {
		return fmt.Errorf("failed to read manifest: %w", err)
	}

	var manifest []struct {
		Config string   `json:"Config"`
		Layers []string `json:"Layers"`
	}
	if err := json.Unmarshal(manifestData, &manifest); err != nil {
		return fmt.Errorf("failed to parse manifest: %w", err)
	}

	if len(manifest) == 0 {
		return fmt.Errorf("no images in manifest")
	}

	// Security: Validate config path doesn't escape tempDir
	if manifest[0].Config != "" {
		if err := ValidateManifestPath(manifest[0].Config); err != nil {
			return fmt.Errorf("invalid config path in manifest: %w", err)
		}

		configSource := filepath.Join(tempDir, manifest[0].Config)
		// Re-validate the joined path
		if err := ValidateFilePath(tempDir, configSource); err != nil {
			return fmt.Errorf("config path validation failed: %w", err)
		}

		configDest := filepath.Join(extractDir, "config.json")
		if err := ValidateFilePath(extractDir, configDest); err != nil {
			return fmt.Errorf("config destination validation failed: %w", err)
		}

		data, err := os.ReadFile(configSource)
		if err != nil {
			return fmt.Errorf("read image config: %w", err)
		}
		if err := os.WriteFile(configDest, data, 0600); err != nil {
			return fmt.Errorf("copy image config: %w", err)
		}
	} else {
		return fmt.Errorf("image manifest has no config")
	}

	// Extract layers in order to create rootfs
	for _, layerPath := range manifest[0].Layers {
		// Security: Validate layer path
		if err := ValidateLayerPath(layerPath); err != nil {
			return fmt.Errorf("invalid layer path %q: %w", layerPath, err)
		}

		fullPath := filepath.Join(tempDir, layerPath)
		// Re-validate the joined path
		if err := ValidateFilePath(tempDir, fullPath); err != nil {
			return fmt.Errorf("layer path %q escapes temporary directory: %w", layerPath, err)
		}

		cmd, err := SafeCommand("tar", "-xf", fullPath, "-C", extractDir)
		if err != nil {
			return fmt.Errorf("prepare layer extraction for %q: %w", layerPath, err)
		}
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("extract layer %q: %w", layerPath, err)
		}
	}

	return nil
}

func installRuntimeNetworkConfig(rootDir string) error {
	etcDir := filepath.Join(rootDir, "etc")
	if err := os.MkdirAll(etcDir, 0755); err != nil {
		return err
	}

	for _, name := range []string{"resolv.conf", "hosts", "nsswitch.conf"} {
		source := filepath.Join("/etc", name)
		data, err := os.ReadFile(source)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return err
		}

		dest := filepath.Join(etcDir, name)
		if err := ValidateFilePath(rootDir, dest); err != nil {
			return err
		}
		if err := os.WriteFile(dest, data, 0644); err != nil {
			return err
		}
	}

	return nil
}

func buildEnvironment(imageConfig *ImageConfig, userEnv map[string]string, port int, imageHash string) []string {
	env := make(map[string]string)

	// Start with image environment
	if imageConfig != nil {
		for k, v := range ParseEnv(imageConfig.Env) {
			env[k] = v
		}
	}

	// Apply user environment (overrides image)
	// Security: Validate environment variable names
	for k, v := range userEnv {
		// Only allow valid environment variable names
		if isValidEnvVarName(k) {
			env[k] = v
		} else {
			logger.Warn("Skipping invalid environment variable name", "name", k)
		}
	}

	// Set activation-specific variables
	env["MCP_PORT"] = fmt.Sprintf("%d", port)
	env["PORT"] = fmt.Sprintf("%d", port)
	env["MCP_IMAGE_HASH"] = imageHash

	// Convert to KEY=value format
	result := make([]string, 0, len(env))
	for k, v := range env {
		result = append(result, fmt.Sprintf("%s=%s", k, v))
	}

	return result
}

// isValidEnvVarName checks if a string is a valid environment variable name
func isValidEnvVarName(name string) bool {
	if name == "" {
		return false
	}
	// Must start with letter or underscore
	if (name[0] < 'A' || name[0] > 'Z') && (name[0] < 'a' || name[0] > 'z') && name[0] != '_' {
		return false
	}
	// Can contain letters, digits, and underscores
	for i := 1; i < len(name); i++ {
		c := name[i]
		if (c < 'A' || c > 'Z') && (c < 'a' || c > 'z') && (c < '0' || c > '9') && c != '_' {
			return false
		}
	}
	return true
}

func startContainer(rootDir, workingDir string, entrypoint, command []string, env []string) error {
	// Combine entrypoint and command
	args := append(entrypoint, command...)
	if len(args) == 0 {
		return fmt.Errorf("no command to execute")
	}
	containerWorkDir := normalizeContainerWorkDir(workingDir)
	hostWorkDir := filepath.Join(rootDir, strings.TrimPrefix(containerWorkDir, "/"))
	if err := os.MkdirAll(hostWorkDir, 0750); err != nil {
		return fmt.Errorf("failed to prepare working directory: %w", err)
	}

	logger.Info("Starting container",
		"executable", args[0],
		"args", args[1:],
		"working_dir", containerWorkDir,
	)

	// Security: Validate the executable path
	if err := SanitizeCommandArg(args[0]); err != nil {
		return fmt.Errorf("invalid executable: %w", err)
	}
	wrapperPath, err := installChrootEntrypointWrapper(rootDir)
	if err != nil {
		return fmt.Errorf("failed to prepare chroot entrypoint wrapper: %w", err)
	}

	// Try chroot first (requires CAP_SYS_CHROOT). Use the image WORKDIR so
	// relative ENTRYPOINT/CMD values like ["python", "bridge.py"] behave as
	// they do under a regular container runtime.
	chrootArgs := append([]string{rootDir, wrapperPath}, args...)
	cmd, err := SafeCommand("chroot", chrootArgs...)
	if err != nil {
		return fmt.Errorf("invalid chroot command: %w", err)
	}
	cmd.Env = append(env, "MCP_WORKDIR="+containerWorkDir)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Setpgid: true,
	}
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("refusing to execute image without chroot isolation: %w", err)
	}

	mcpProcess = cmd.Process
	logger.Info("Container process started", "pid", mcpProcess.Pid)

	return nil
}

func installChrootEntrypointWrapper(rootDir string) (string, error) {
	const wrapperPath = "/agentarea-entrypoint-wrapper"
	wrapperHostPath := filepath.Join(rootDir, strings.TrimPrefix(wrapperPath, "/"))
	if err := ValidateFilePath(rootDir, wrapperHostPath); err != nil {
		return "", err
	}
	content := []byte("#!/bin/sh\ncd \"${MCP_WORKDIR:-/}\" || exit 127\nexec \"$@\"\n")
	if err := os.WriteFile(wrapperHostPath, content, 0o755); err != nil {
		return "", err
	}
	return wrapperPath, nil
}

func normalizeContainerWorkDir(workingDir string) string {
	if workingDir == "" {
		return "/"
	}
	if !strings.HasPrefix(workingDir, "/") {
		workingDir = "/" + workingDir
	}
	return filepath.Clean(workingDir)
}

const (
	defaultOutputCaptureBytes int64 = 1024 * 1024
	maxOutputCaptureBytes     int64 = 16 * 1024 * 1024
)

// ExecuteRequest represents a manager-authorized command execution request.
// The normal manager path materializes immutable task inputs through its
// WorkspaceProvider before forwarding this command. The hydration fields stay
// available only for compatibility with the older direct activation contract.
type ExecuteRequest struct {
	ExecutorIncarnation  string                 `json:"executor_incarnation,omitempty"`
	CommandBody          string                 `json:"command_body,omitempty"`
	CommandPath          string                 `json:"command_path,omitempty"`
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

const maxCommandBodyBytes = 256 * 1024

// SandboxArtifact is a file produced by a sandbox command and requested by the caller.
type SandboxArtifact struct {
	Path        string `json:"path"`
	Name        string `json:"name,omitempty"`
	ContentType string `json:"content_type,omitempty"`
	Size        int64  `json:"size,omitempty"`
	SHA256      string `json:"sha256,omitempty"`
	Error       string `json:"error,omitempty"`
}

// ExecuteResponse represents the result of script execution.
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

func executeHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	beginRequest()
	defer endRequest()

	body, err := readActivationRequestBody(r)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid request: %v"}`, err), http.StatusBadRequest)
		return
	}
	req, err := decodeExecuteRequest(bytes.NewReader(body))
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid request: %v"}`, err), http.StatusBadRequest)
		return
	}

	if req.CommandBody == "" {
		http.Error(w, `{"error": "command_body is required"}`, http.StatusBadRequest)
		return
	}
	if len(req.CommandBody) > maxCommandBodyBytes || strings.ContainsRune(req.CommandBody, 0) {
		http.Error(w, `{"error": "command_body is too large or malformed"}`, http.StatusBadRequest)
		return
	}
	if req.TaskID == "" || req.WorkspaceID == "" {
		http.Error(w, `{"error": "task_id and workspace_id are required"}`, http.StatusBadRequest)
		return
	}
	if !authorizeActivationRequest(w, r, activationauth.ScopeExecute, activationauth.Identity{
		WorkspaceID: req.WorkspaceID, TaskID: req.TaskID,
		Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(body)) {
		return
	}
	if !requireExecutorIncarnation(w, req.ExecutorIncarnation) {
		return
	}
	runtimeManifest, err := runtimeinfo.Load(runtimeinfo.PathFromEnv())
	if err != nil {
		http.Error(w, `{"error": "runtime manifest unavailable"}`, http.StatusServiceUnavailable)
		return
	}
	unlockWorkspace := lockWorkspaceMutation(req.WorkspaceID, req.TaskID)
	defer unlockWorkspace()

	stdoutLimit, err := outputCaptureLimit(req.StdoutMaxBytes)
	if err != nil {
		http.Error(w, `{"error": "invalid stdout_max_bytes"}`, http.StatusBadRequest)
		return
	}
	stderrLimit, err := outputCaptureLimit(req.StderrMaxBytes)
	if err != nil {
		http.Error(w, `{"error": "invalid stderr_max_bytes"}`, http.StatusBadRequest)
		return
	}

	maxTimeout := servicePolicy.MaxExecutionTimeoutSeconds
	if req.TimeoutSeconds <= 0 || req.TimeoutSeconds > maxTimeout {
		http.Error(
			w,
			fmt.Sprintf(`{"error": "timeout_seconds must be between 1 and %d"}`, maxTimeout),
			http.StatusBadRequest,
		)
		return
	}
	timeout := req.TimeoutSeconds

	workspaceDir, err := resolveExecutionWorkspace(req.WorkspaceID, req.TaskID)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusBadRequest)
		return
	}
	// Resolve the non-root identity to run the untrusted command as. When the
	// service runs as root this MUST succeed; running untrusted code as root
	// would expose PID1's environment (incl. the activation secret) via /proc.
	credential, err := sandboxCommandCredential()
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusInternalServerError)
		return
	}
	if credential != nil &&
		(credential.Uid != runtimeManifest.ExecutionSupervisor.CommandUID || credential.Gid != runtimeManifest.ExecutionSupervisor.CommandGID) {
		http.Error(w, `{"error": "runtime supervisor identity disagrees with activation policy"}`, http.StatusServiceUnavailable)
		return
	}
	if err := prepareTaskWorkspace(workspaceDir, credential); err != nil {
		http.Error(w, `{"error": "failed to prepare non-root task workspace"}`, http.StatusInternalServerError)
		return
	}
	// The control script lives outside /workspace so it neither consumes the
	// user's file quota nor becomes visible to workspace inspection.
	commandFile, err := os.CreateTemp("", "agentarea-command-*.sh")
	if err != nil {
		http.Error(w, `{"error": "failed to create command file"}`, http.StatusInternalServerError)
		return
	}
	defer func() {
		_ = commandFile.Close()
		_ = os.Remove(commandFile.Name())
	}()
	if _, err := io.WriteString(commandFile, req.CommandBody); err != nil {
		http.Error(w, `{"error": "failed to write command"}`, http.StatusInternalServerError)
		return
	}
	if err := prepareOwnedFile(commandFile, credential, 0o500); err != nil {
		http.Error(w, `{"error": "failed to prepare command ownership"}`, http.StatusInternalServerError)
		return
	}
	if err := commandFile.Close(); err != nil {
		http.Error(w, `{"error": "failed to close command file"}`, http.StatusInternalServerError)
		return
	}
	// Capture output
	stdout := newBoundedBuffer(stdoutLimit)
	stderr := newBoundedBuffer(stderrLimit)
	start := time.Now()
	status, executionErr := runSandboxCommand(r.Context(), supervisedCommandRequest{
		Attestation: runtimeManifest.ExecutionSupervisor, CommandPath: commandFile.Name(),
		WorkspaceDir: workspaceDir, Environment: sandboxExecutionEnvironment(req.WorkspaceID, req.TaskID, workspaceDir),
		TimeoutSeconds: timeout, MaxFileBytes: servicePolicy.WorkspaceLimits.MaxFileBytes,
		Stdout: stdout, Stderr: stderr,
	})
	if executionErr != nil {
		rejectUnsafeExecutor(w, workspaceDir, executionErr)
		return
	}
	postExecutionCtx, cancelPostExecution := context.WithTimeout(context.WithoutCancel(r.Context()), execsupervisor.PostExecutionBudget)
	defer cancelPostExecution()
	workspaceAuditErr := enforceWorkspaceLimitsContext(postExecutionCtx, workspaceDir, servicePolicy.WorkspaceLimits)
	if workspaceAuditErr != nil {
		rejectUnsafeWorkspace(w, workspaceDir, workspaceAuditErr)
		return
	}
	if status.TimedOut {
		if stderr.Len() > 0 {
			_, _ = stderr.Write([]byte("\n"))
		}
		_, _ = stderr.Write([]byte("execution timed out"))
	}
	changes, changesErr := collectWorkspaceChangesContext(postExecutionCtx, workspaceDir, req.WorkspaceHydration)
	if changesErr != nil {
		rejectUnsafeWorkspace(w, workspaceDir, fmt.Errorf("describe workspace changes: %w", changesErr))
		return
	}
	artifacts, artifactErr := collectArtifactsContext(postExecutionCtx, workspaceDir, req.ArtifactPaths)
	if artifactErr != nil {
		rejectUnsafeWorkspace(w, workspaceDir, fmt.Errorf("inspect requested artifacts: %w", artifactErr))
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(ExecuteResponse{
		Stdout: stdout.String(), Stderr: stderr.String(),
		StdoutTruncated: stdout.Truncated(), StderrTruncated: stderr.Truncated(),
		ExitCode: status.ChildExitCode, ExecutionTimeMs: time.Since(start).Milliseconds(),
		Artifacts: artifacts, WorkspaceChanges: changes,
	})

	logger.Info("Script executed",
		"task_id", req.TaskID,
		"stdout_bytes", stdout.Len(),
		"elapsed_ms", time.Since(start).Milliseconds(),
	)
}

func rejectUnsafeExecutor(w http.ResponseWriter, workspaceDir string, executionErr error) {
	cleanupErr := os.RemoveAll(workspaceDir)
	logger.Error("execution quiescence could not be proven", "workspace", workspaceDir, "error", executionErr, "cleanup_error", cleanupErr)
	w.Header().Set("X-Agentarea-Executor-Unsafe", "true")
	w.Header().Set("Connection", "close")
	http.Error(w, `{"error": "execution quiescence unavailable; sandbox executor invalidated"}`, http.StatusServiceUnavailable)
	executorInvalidator()
}

func decodeExecuteRequest(body io.Reader) (*ExecuteRequest, error) {
	data, err := io.ReadAll(io.LimitReader(body, maxActivationRequestBytes+1))
	if err != nil || len(data) > maxActivationRequestBytes {
		return nil, fmt.Errorf("request body exceeds command limit")
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return nil, err
	}
	for _, field := range []string{"args", "env", "script", "input_files", "content_base64", "script_content", "script_name"} {
		if _, exists := fields[field]; exists {
			return nil, fmt.Errorf("unsupported_contract_version: inline execution fields are not supported; use command_body and manager-owned task inputs")
		}
	}
	var req ExecuteRequest
	if err := json.Unmarshal(data, &req); err != nil {
		return nil, err
	}
	return &req, nil
}

type boundedBuffer struct {
	buffer    bytes.Buffer
	limit     int64
	truncated bool
}

func newBoundedBuffer(limit int64) *boundedBuffer {
	return &boundedBuffer{limit: limit}
}

func (b *boundedBuffer) Write(data []byte) (int, error) {
	originalLength := len(data)
	remaining := b.limit - int64(b.buffer.Len())
	if remaining <= 0 {
		b.truncated = b.truncated || originalLength > 0
		return originalLength, nil
	}
	if int64(len(data)) > remaining {
		data = data[:remaining]
		b.truncated = true
	}
	_, _ = b.buffer.Write(data)
	return originalLength, nil
}

func (b *boundedBuffer) String() string { return b.buffer.String() }

func (b *boundedBuffer) Len() int { return b.buffer.Len() }

func (b *boundedBuffer) Truncated() bool { return b.truncated }

func outputCaptureLimit(requested int64) (int64, error) {
	if requested == 0 {
		return defaultOutputCaptureBytes, nil
	}
	if requested < 0 || requested > maxOutputCaptureBytes {
		return 0, fmt.Errorf("capture limit must be between 1 and %d bytes", maxOutputCaptureBytes)
	}
	return requested, nil
}

func collectArtifacts(workspace string, paths []string) []SandboxArtifact {
	artifacts, _ := collectArtifactsContext(context.Background(), workspace, paths)
	return artifacts
}

func collectArtifactsContext(ctx context.Context, workspace string, paths []string) ([]SandboxArtifact, error) {
	if len(paths) == 0 {
		// Durable publication is explicit through the artifact tool. Returning
		// every file that happens to look deliverable makes temporary files and
		// manager-owned markers part of the user contract by accident.
		return nil, nil
	}

	root, err := os.OpenRoot(workspace)
	if err != nil {
		return []SandboxArtifact{{Error: fmt.Sprintf("failed to open workspace root: %s", err)}}, nil
	}
	defer root.Close()

	artifacts := make([]SandboxArtifact, 0, len(paths))
	for _, requested := range paths {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		artifact := SandboxArtifact{Path: requested, Name: filepath.Base(requested)}
		clean, err := cleanSandboxRelativePath(requested)
		if err != nil {
			artifact.Error = err.Error()
			artifacts = append(artifacts, artifact)
			continue
		}

		info, err := root.Stat(clean)
		if err != nil {
			artifact.Error = err.Error()
			artifacts = append(artifacts, artifact)
			continue
		}
		if info.IsDir() {
			artifact.Error = "artifact path is a directory"
			artifacts = append(artifacts, artifact)
			continue
		}
		file, err := root.Open(clean)
		if err != nil {
			artifact.Error = err.Error()
			artifacts = append(artifacts, artifact)
			continue
		}
		prefix := make([]byte, 512)
		prefixBytes, _ := io.ReadFull(file, prefix)
		_, _ = file.Seek(0, io.SeekStart)
		hasher := sha256.New()
		_, hashErr := copyWithContext(ctx, hasher, file)
		file.Close()
		if hashErr != nil {
			artifact.Error = hashErr.Error()
			artifacts = append(artifacts, artifact)
			continue
		}
		artifact.Size = info.Size()
		artifact.ContentType = http.DetectContentType(prefix[:prefixBytes])
		artifact.SHA256 = hex.EncodeToString(hasher.Sum(nil))
		artifacts = append(artifacts, artifact)
	}

	return artifacts, nil
}

func collectWorkspaceChanges(workspaceDir string, hydration *workspace.Hydration) ([]workspace.ChangeDescriptor, error) {
	return collectWorkspaceChangesContext(context.Background(), workspaceDir, hydration)
}

func collectWorkspaceChangesContext(ctx context.Context, workspaceDir string, hydration *workspace.Hydration) ([]workspace.ChangeDescriptor, error) {
	if hydration == nil {
		return nil, nil
	}
	baseline := make(map[string]workspace.Download, len(hydration.Downloads))
	for _, entry := range hydration.Downloads {
		baseline[entry.RelativePath] = entry
	}
	changes := make([]workspace.ChangeDescriptor, 0)
	err := filepath.WalkDir(workspaceDir, func(localPath string, entry os.DirEntry, walkErr error) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		if walkErr != nil {
			return walkErr
		}
		rel, err := filepath.Rel(workspaceDir, localPath)
		if err != nil || rel == "." {
			return nil
		}
		rel = filepath.ToSlash(rel)
		if entry.IsDir() {
			if shouldSkipTrackedWorkspaceDir(rel) {
				return filepath.SkipDir
			}
			return nil
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return nil
		}
		info, err := entry.Info()
		if err != nil || !info.Mode().IsRegular() {
			return nil
		}
		file, err := os.Open(localPath)
		if err != nil {
			return err
		}
		prefix := make([]byte, 512)
		prefixBytes, _ := io.ReadFull(file, prefix)
		_, _ = file.Seek(0, io.SeekStart)
		hasher := sha256.New()
		_, err = copyWithContext(ctx, hasher, file)
		file.Close()
		if err != nil {
			return err
		}
		hash := hex.EncodeToString(hasher.Sum(nil))
		if previous, exists := baseline[rel]; exists && previous.SHA256 == hash && previous.Size == info.Size() {
			delete(baseline, rel)
			return nil
		}
		delete(baseline, rel)
		changes = append(changes, workspace.ChangeDescriptor{
			RelativePath: rel,
			SHA256:       hash,
			Size:         info.Size(),
			ContentType:  http.DetectContentType(prefix[:prefixBytes]),
			Mode:         uint32(info.Mode().Perm()),
		})
		return nil
	})
	if err != nil {
		return nil, err
	}
	for rel := range baseline {
		changes = append(changes, workspace.ChangeDescriptor{RelativePath: rel, Deleted: true})
	}
	sort.Slice(changes, func(i, j int) bool { return changes[i].RelativePath < changes[j].RelativePath })
	return changes, nil
}

func sandboxProcessEnvironment() []string {
	env := os.Environ()
	filtered := make([]string, 0, len(env))
	for _, item := range env {
		name, _, found := strings.Cut(item, "=")
		if found && (isStorageCredentialEnv(name) || isSandboxIdentityEnv(name)) {
			continue
		}
		filtered = append(filtered, item)
	}
	return filtered
}

func isSandboxIdentityEnv(name string) bool {
	switch name {
	case "AGENTAREA_WORKSPACE_ID", "AGENTAREA_TASK_ID", "AGENTAREA_WORKSPACE_ROOT", "AGENTAREA_INPUT_DIR":
		return true
	default:
		return false
	}
}

func sandboxExecutionEnvironment(workspaceID, taskID, workspaceDir string) []string {
	return append(
		sandboxProcessEnvironment(),
		"AGENTAREA_WORKSPACE_ID="+workspaceID,
		"AGENTAREA_TASK_ID="+taskID,
		"AGENTAREA_WORKSPACE_ROOT="+workspaceDir,
		"AGENTAREA_INPUT_DIR=inputs",
	)
}

func isStorageCredentialEnv(name string) bool {
	switch strings.ToUpper(name) {
	case "AWS_ACCESS_KEY_ID",
		"AWS_SECRET_ACCESS_KEY",
		"AWS_SESSION_TOKEN",
		"AWS_SECURITY_TOKEN",
		"AWS_WEB_IDENTITY_TOKEN_FILE",
		"AWS_SHARED_CREDENTIALS_FILE",
		"AWS_CONTAINER_AUTHORIZATION_TOKEN",
		"AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
		"AWS_CONTAINER_CREDENTIALS_FULL_URI",
		"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
		"RUSTFS_ACCESS_KEY",
		"RUSTFS_SECRET_KEY",
		"MINIO_ROOT_USER",
		"MINIO_ROOT_PASSWORD",
		"S3_ACCESS_KEY",
		"S3_SECRET_KEY",
		activationauth.SecretEnv:
		return true
	default:
		return strings.HasPrefix(strings.ToUpper(name), "SANDBOX_WORKSPACE_S3_CREDENTIAL")
	}
}

func shouldSkipTrackedWorkspaceDir(rel string) bool {
	for _, part := range strings.Split(rel, "/") {
		switch strings.ToLower(part) {
		case ".cache", ".git", ".npm", ".venv", "__pycache__", "node_modules", "site-packages":
			return true
		}
	}
	return false
}

func cleanSandboxRelativePath(path string) (string, error) {
	clean := filepath.Clean(path)
	if path == "" || filepath.IsAbs(path) || strings.HasPrefix(clean, "..") || strings.Contains(clean, string(filepath.Separator)+".."+string(filepath.Separator)) {
		return "", fmt.Errorf("path must be relative and must not contain '..'")
	}
	return clean, nil
}

var autoArtifactExtensions = map[string]bool{
	".csv":  true,
	".docx": true,
	".gif":  true,
	".jpeg": true,
	".jpg":  true,
	".json": true,
	".md":   true,
	".pdf":  true,
	".png":  true,
	".pptx": true,
	".svg":  true,
	".txt":  true,
	".webp": true,
	".xlsx": true,
}

var autoArtifactIgnoredDirs = map[string]bool{
	".cache":        true,
	".git":          true,
	".npm":          true,
	".venv":         true,
	"__pycache__":   true,
	"inputs":        true,
	"node_modules":  true,
	"site-packages": true,
}

var autoArtifactIgnoredNames = map[string]bool{
	"authors":          true,
	"authors.txt":      true,
	"cmd.sh":           true,
	"entry_points.txt": true,
	"license":          true,
	"license.md":       true,
	"license.txt":      true,
	"licenses.txt":     true,
	"readme":           true,
	"readme.md":        true,
	"readme.txt":       true,
	"top_level.txt":    true,
}

type autoArtifactCandidate struct {
	path    string
	modTime time.Time
	size    int64
}

func discoverAutoArtifacts(workspace string, since time.Time) []string {
	candidates := make([]autoArtifactCandidate, 0)
	_ = filepath.WalkDir(workspace, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		rel, relErr := filepath.Rel(workspace, path)
		if relErr != nil || rel == "." {
			return nil
		}
		rel = filepath.ToSlash(rel)
		if entry.IsDir() {
			if shouldSkipAutoArtifactDir(rel) {
				return filepath.SkipDir
			}
			return nil
		}
		if shouldSkipAutoArtifactFile(rel) {
			return nil
		}
		if !autoArtifactExtensions[strings.ToLower(filepath.Ext(rel))] {
			return nil
		}
		info, infoErr := entry.Info()
		if infoErr != nil || info.IsDir() || info.Size() <= 0 {
			return nil
		}
		// Collect any allow-listed workspace file by PRESENCE, not mtime: a
		// deliverable created in an earlier step (e.g. a chart PNG) must still
		// be published even though a later command touched nothing. Cache dirs
		// and the extension allow-list bound the set; dedup by content hash
		// makes re-collecting an unchanged file harmless.
		candidates = append(candidates, autoArtifactCandidate{
			path:    rel,
			modTime: info.ModTime(),
			size:    info.Size(),
		})
		return nil
	})

	sort.SliceStable(candidates, func(i, j int) bool {
		if candidates[i].modTime.Equal(candidates[j].modTime) {
			return candidates[i].path < candidates[j].path
		}
		return candidates[i].modTime.After(candidates[j].modTime)
	})
	paths := make([]string, 0, len(candidates))
	for _, candidate := range candidates {
		paths = append(paths, candidate.path)
	}
	return paths
}

func shouldSkipAutoArtifactDir(rel string) bool {
	if rel == "" || rel == "." {
		return false
	}
	for _, part := range strings.Split(rel, "/") {
		lower := strings.ToLower(part)
		if autoArtifactIgnoredDirs[lower] || strings.HasSuffix(lower, ".dist-info") || strings.HasSuffix(lower, ".egg-info") {
			return true
		}
	}
	return false
}

func shouldSkipAutoArtifactFile(rel string) bool {
	if rel == "" || strings.HasPrefix(rel, "inputs/") {
		return true
	}
	base := strings.ToLower(filepath.Base(rel))
	if autoArtifactIgnoredNames[base] {
		return true
	}
	return strings.HasPrefix(base, ".")
}

// maxFileContentBytes bounds the inline JSON/base64 endpoint.
// The raw /files/content endpoint is governed by the control-plane workspace
// quota and streams directly to disk.
const maxFileContentBytes = 16 * 1024 * 1024

// FilesPutRequest writes a single file into the per-task workspace on the same
// filesystem bash executes against, so the agent's file tool and its shell see
// one workspace.
type FilesPutRequest struct {
	WorkspaceID         string `json:"workspace_id"`
	TaskID              string `json:"task_id"`
	ExecutorIncarnation string `json:"executor_incarnation,omitempty"`
	Path                string `json:"path"`
	ContentBase64       string `json:"content_base64"`
}

// FilesPutResponse acknowledges a written file.
type FilesPutResponse struct {
	Path string `json:"path"`
	Size int64  `json:"size"`
}

// FilesGetResponse returns a single file's contents.
type FilesGetResponse struct {
	ContentBase64 string `json:"content_base64"`
	Size          int64  `json:"size"`
}

// FilesListResponse lists the regular files under a prefix.
type FilesListResponse struct {
	Paths []string `json:"paths"`
}

// filesHandler serves the sandbox file API. Writes and reads target the same
// per-task workspace directory the /execute command runs in, giving the agent's
// file tool and its bash a shared filesystem.
func filesHandler(w http.ResponseWriter, r *http.Request) {
	beginRequest()
	defer endRequest()
	switch r.Method {
	case http.MethodPut:
		filesPutHandler(w, r)
	case http.MethodGet:
		filesGetHandler(w, r)
	default:
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
	}
}

// fileContentHandler is the constant-memory transfer path used for task input
// hydration, artifact publication, and larger file-tool operations. The inline
// /files JSON/base64 endpoint remains bounded for compatibility with old
// clients; durable/live file movement must use this raw stream instead.
func fileContentHandler(w http.ResponseWriter, r *http.Request) {
	beginRequest()
	defer endRequest()
	switch r.Method {
	case http.MethodPut:
		fileContentPutHandler(w, r)
	case http.MethodGet:
		fileContentGetHandler(w, r)
	default:
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
	}
}

func fileContentPutHandler(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query()
	workspaceID := query.Get("workspace_id")
	taskID := query.Get("task_id")
	executorIncarnation := query.Get("executor_incarnation")
	pathParam := query.Get("path")
	expectedSHA256 := query.Get("sha256")
	expectedSize, sizeErr := strconv.ParseInt(query.Get("size"), 10, 64)
	modeValue, modeErr := strconv.ParseUint(query.Get("mode"), 8, 32)
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		http.Error(w, `{"error": "invalid workspace_id"}`, http.StatusBadRequest)
		return
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		http.Error(w, `{"error": "invalid task_id"}`, http.StatusBadRequest)
		return
	}
	clean, pathErr := cleanSandboxRelativePath(pathParam)
	digest, digestErr := hex.DecodeString(expectedSHA256)
	if pathErr != nil || strings.ContainsRune(pathParam, 0) || sizeErr != nil || expectedSize < 0 || modeErr != nil || modeValue == 0 || modeValue&^uint64(0o777) != 0 || digestErr != nil || len(digest) != sha256.Size || expectedSHA256 != strings.ToLower(expectedSHA256) {
		http.Error(w, `{"error": "path, size, mode, and lowercase sha256 are required"}`, http.StatusBadRequest)
		return
	}
	if expectedSize > servicePolicy.WorkspaceLimits.MaxFileBytes {
		http.Error(w, `{"error": "file exceeds workspace per-file limit"}`, http.StatusRequestEntityTooLarge)
		return
	}
	if r.ContentLength != expectedSize {
		http.Error(w, `{"error": "Content-Length does not match declared size"}`, http.StatusBadRequest)
		return
	}
	if !authorizeActivationRequest(w, r, activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BoundTransferSHA256(http.MethodPut, clean, expectedSize, uint32(modeValue), expectedSHA256, executorIncarnation)) {
		return
	}
	if !requireExecutorIncarnation(w, executorIncarnation) {
		return
	}
	unlockWorkspace := lockWorkspaceMutation(workspaceID, taskID)
	defer unlockWorkspace()

	credential, err := sandboxCommandCredential()
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": %q}`, err.Error()), http.StatusInternalServerError)
		return
	}
	workspaceDir, err := resolveExecutionWorkspace(workspaceID, taskID)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": %q}`, err.Error()), http.StatusBadRequest)
		return
	}
	if err := prepareTaskWorkspace(workspaceDir, credential); err != nil {
		http.Error(w, `{"error": "failed to prepare non-root task workspace"}`, http.StatusInternalServerError)
		return
	}
	root, err := os.OpenRoot(workspaceDir)
	if err != nil {
		http.Error(w, `{"error": "task workspace is unavailable"}`, http.StatusInternalServerError)
		return
	}
	defer root.Close()
	if err := ensureWorkspaceFileSlot(root, workspaceDir, clean); err != nil {
		http.Error(w, `{"error": "workspace file limit exceeded"}`, http.StatusInsufficientStorage)
		return
	}
	dir := filepath.Dir(clean)
	if dir != "." {
		if err := root.MkdirAll(dir, 0o700); err != nil {
			http.Error(w, `{"error": "failed to create parent directory"}`, http.StatusInternalServerError)
			return
		}
	}
	tempName, err := streamedUploadTempName(dir, filepath.Base(clean))
	if err != nil {
		http.Error(w, `{"error": "failed to create upload identity"}`, http.StatusInternalServerError)
		return
	}
	temp, err := root.OpenFile(tempName, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		http.Error(w, `{"error": "failed to create temporary upload"}`, http.StatusInternalServerError)
		return
	}
	removeTemp := true
	defer func() {
		_ = temp.Close()
		if removeTemp {
			_ = root.Remove(tempName)
		}
	}()
	hasher := sha256.New()
	written, copyErr := io.Copy(io.MultiWriter(temp, hasher), io.LimitReader(r.Body, expectedSize+1))
	if copyErr != nil || written != expectedSize || hex.EncodeToString(hasher.Sum(nil)) != expectedSHA256 {
		http.Error(w, `{"error": "streamed file size or checksum mismatch"}`, http.StatusBadRequest)
		return
	}
	if err := temp.Sync(); err != nil {
		http.Error(w, `{"error": "failed to sync streamed file"}`, http.StatusInternalServerError)
		return
	}
	if err := prepareOwnedFile(temp, credential, fs.FileMode(modeValue)); err != nil {
		http.Error(w, `{"error": "failed to prepare streamed file ownership"}`, http.StatusInternalServerError)
		return
	}
	if err := temp.Close(); err != nil {
		http.Error(w, `{"error": "failed to close streamed file"}`, http.StatusInternalServerError)
		return
	}
	if err := root.Rename(tempName, clean); err != nil {
		http.Error(w, `{"error": "failed to commit streamed file"}`, http.StatusInternalServerError)
		return
	}
	removeTemp = false
	if err := enforceWorkspaceLimits(workspaceDir, servicePolicy.WorkspaceLimits); err != nil {
		rejectUnsafeWorkspace(w, workspaceDir, err)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(FilesPutResponse{Path: clean, Size: written})
}

func fileContentGetHandler(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query()
	workspaceID := query.Get("workspace_id")
	taskID := query.Get("task_id")
	executorIncarnation := query.Get("executor_incarnation")
	pathParam := query.Get("path")
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		http.Error(w, `{"error": "invalid workspace_id"}`, http.StatusBadRequest)
		return
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		http.Error(w, `{"error": "invalid task_id"}`, http.StatusBadRequest)
		return
	}
	clean, err := cleanSandboxRelativePath(pathParam)
	if err != nil || strings.ContainsRune(pathParam, 0) {
		http.Error(w, `{"error": "path must be relative and canonical"}`, http.StatusBadRequest)
		return
	}
	if !authorizeActivationRequest(w, r, activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BoundTransferSHA256(http.MethodGet, clean, -1, 0, activationauth.BodySHA256(nil), executorIncarnation)) {
		return
	}
	if !requireExecutorIncarnation(w, executorIncarnation) {
		return
	}
	workspaceDir, err := existingExecutionWorkspace(workspaceID, taskID)
	if errors.Is(err, os.ErrNotExist) {
		http.Error(w, `{"error": "task workspace expired"}`, http.StatusGone)
		return
	}
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": %q}`, err.Error()), http.StatusBadRequest)
		return
	}
	root, err := os.OpenRoot(workspaceDir)
	if err != nil {
		http.Error(w, `{"error": "task workspace is unavailable"}`, http.StatusInternalServerError)
		return
	}
	defer root.Close()
	info, err := root.Stat(clean)
	if err != nil {
		http.Error(w, `{"error": "file not found"}`, http.StatusNotFound)
		return
	}
	if info.IsDir() {
		http.Error(w, `{"error": "path is a directory"}`, http.StatusBadRequest)
		return
	}
	file, err := root.Open(clean)
	if err != nil {
		http.Error(w, `{"error": "file not found"}`, http.StatusNotFound)
		return
	}
	defer file.Close()
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Length", strconv.FormatInt(info.Size(), 10))
	w.Header().Set("X-AgentArea-File-Mode", fmt.Sprintf("%03o", info.Mode().Perm()))
	if _, err := io.Copy(w, file); err != nil {
		logger.Error("stream sandbox file", "workspace_id", workspaceID, "task_id", taskID, "path", clean, "error", err)
	}
}

func streamedUploadTempName(dir, base string) (string, error) {
	random := make([]byte, 16)
	if _, err := rand.Read(random); err != nil {
		return "", err
	}
	name := "." + base + ".agentarea-upload-" + hex.EncodeToString(random)
	if dir == "." {
		return name, nil
	}
	return filepath.Join(dir, name), nil
}

// workspaceTaskHandler removes one exact live task directory. Durable inputs
// and explicitly published artifacts remain in object storage; this endpoint
// owns only the executor's ephemeral working copy.
func workspaceTaskHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodDelete {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}
	beginRequest()
	defer endRequest()

	workspaceID := r.URL.Query().Get("workspace_id")
	taskID := r.URL.Query().Get("task_id")
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		http.Error(w, `{"error": "invalid workspace_id"}`, http.StatusBadRequest)
		return
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		http.Error(w, `{"error": "invalid task_id"}`, http.StatusBadRequest)
		return
	}
	if !authorizeActivationRequest(w, r, activationauth.ScopeCleanup, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(nil)) {
		return
	}
	unlockWorkspace := lockWorkspaceMutation(workspaceID, taskID)
	defer unlockWorkspace()

	dir, err := executionWorkspacePath(workspaceID, taskID)
	if err != nil {
		http.Error(w, `{"error": "invalid task workspace"}`, http.StatusBadRequest)
		return
	}
	if err := os.RemoveAll(dir); err != nil {
		http.Error(w, `{"error": "failed to delete task workspace"}`, http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func filesPutHandler(w http.ResponseWriter, r *http.Request) {
	body, err := readActivationRequestBody(r)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid request: %v"}`, err), http.StatusBadRequest)
		return
	}
	var req FilesPutRequest
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid request: %v"}`, err), http.StatusBadRequest)
		return
	}
	if req.WorkspaceID == "" || req.TaskID == "" {
		http.Error(w, `{"error": "workspace_id and task_id are required"}`, http.StatusBadRequest)
		return
	}
	if !authorizeActivationRequest(w, r, activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: req.WorkspaceID, TaskID: req.TaskID, Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(body)) {
		return
	}
	if !requireExecutorIncarnation(w, req.ExecutorIncarnation) {
		return
	}
	unlockWorkspace := lockWorkspaceMutation(req.WorkspaceID, req.TaskID)
	defer unlockWorkspace()
	clean, err := cleanSandboxRelativePath(req.Path)
	if err != nil || strings.ContainsRune(req.Path, 0) {
		http.Error(w, `{"error": "path must be relative and must not contain '..' or NUL"}`, http.StatusBadRequest)
		return
	}
	content, err := base64.StdEncoding.DecodeString(req.ContentBase64)
	if err != nil {
		http.Error(w, `{"error": "content_base64 is not valid base64"}`, http.StatusBadRequest)
		return
	}
	if len(content) > maxFileContentBytes {
		http.Error(w, `{"error": "file content is too large"}`, http.StatusRequestEntityTooLarge)
		return
	}
	if int64(len(content)) > servicePolicy.WorkspaceLimits.MaxFileBytes {
		http.Error(w, `{"error": "file exceeds workspace per-file limit"}`, http.StatusRequestEntityTooLarge)
		return
	}
	// Resolve the non-root identity before writing. When the service runs as
	// root the file MUST end up owned by the sandbox uid, otherwise the bash
	// command (which runs as that uid) could not read or overwrite it.
	credential, err := sandboxCommandCredential()
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusInternalServerError)
		return
	}
	workspaceDir, err := resolveExecutionWorkspace(req.WorkspaceID, req.TaskID)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusBadRequest)
		return
	}
	if err := prepareTaskWorkspace(workspaceDir, credential); err != nil {
		http.Error(w, `{"error": "failed to prepare non-root task workspace"}`, http.StatusInternalServerError)
		return
	}
	root, err := os.OpenRoot(workspaceDir)
	if err != nil {
		http.Error(w, `{"error": "task workspace is unavailable"}`, http.StatusInternalServerError)
		return
	}
	defer root.Close()
	if err := ensureWorkspaceFileSlot(root, workspaceDir, clean); err != nil {
		http.Error(w, `{"error": "workspace file limit exceeded"}`, http.StatusInsufficientStorage)
		return
	}
	if dir := filepath.Dir(clean); dir != "." {
		if err := root.MkdirAll(dir, 0o700); err != nil {
			http.Error(w, `{"error": "failed to create parent directory"}`, http.StatusInternalServerError)
			return
		}
	}
	if err := root.WriteFile(clean, content, 0o600); err != nil {
		http.Error(w, `{"error": "failed to write file"}`, http.StatusInternalServerError)
		return
	}
	written, err := root.OpenFile(clean, os.O_RDONLY, 0)
	if err != nil {
		http.Error(w, `{"error": "failed to reopen written file"}`, http.StatusInternalServerError)
		return
	}
	if err := prepareOwnedFile(written, credential, 0o600); err != nil {
		written.Close()
		http.Error(w, `{"error": "failed to prepare written file ownership"}`, http.StatusInternalServerError)
		return
	}
	_ = written.Close()
	if err := enforceWorkspaceLimits(workspaceDir, servicePolicy.WorkspaceLimits); err != nil {
		rejectUnsafeWorkspace(w, workspaceDir, err)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(FilesPutResponse{Path: clean, Size: int64(len(content))})
}

func filesGetHandler(w http.ResponseWriter, r *http.Request) {
	body, err := readActivationRequestBody(r)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid request: %v"}`, err), http.StatusBadRequest)
		return
	}
	query := r.URL.Query()
	workspaceID := query.Get("workspace_id")
	taskID := query.Get("task_id")
	executorIncarnation := query.Get("executor_incarnation")
	if workspaceID == "" || taskID == "" {
		http.Error(w, `{"error": "workspace_id and task_id are required"}`, http.StatusBadRequest)
		return
	}
	operationPath := ""
	if query.Has("list") {
		prefix := query.Get("list")
		if prefix != "" {
			cleanPrefix, cleanErr := cleanSandboxRelativePath(prefix)
			if cleanErr != nil || cleanPrefix != prefix {
				http.Error(w, `{"error": "list prefix must be relative and canonical"}`, http.StatusBadRequest)
				return
			}
		}
		operationPath = "list:" + prefix
	} else {
		pathParam := query.Get("path")
		clean, cleanErr := cleanSandboxRelativePath(pathParam)
		if cleanErr != nil || strings.ContainsRune(pathParam, 0) {
			http.Error(w, `{"error": "path must be relative and must not contain '..' or NUL"}`, http.StatusBadRequest)
			return
		}
		operationPath = "file:" + clean
	}
	if !authorizeActivationRequest(w, r, activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BoundTransferSHA256(http.MethodGet, operationPath, -1, 0, activationauth.BodySHA256(body), executorIncarnation)) {
		return
	}
	if !requireExecutorIncarnation(w, executorIncarnation) {
		return
	}
	workspaceDir, err := existingExecutionWorkspace(workspaceID, taskID)
	if errors.Is(err, os.ErrNotExist) {
		http.Error(w, `{"error": "task workspace expired"}`, http.StatusGone)
		return
	}
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusBadRequest)
		return
	}
	root, err := os.OpenRoot(workspaceDir)
	if err != nil {
		http.Error(w, `{"error": "task workspace is unavailable"}`, http.StatusInternalServerError)
		return
	}
	defer root.Close()

	if query.Has("list") {
		paths, err := listWorkspaceFiles(root, query.Get("list"))
		if err != nil {
			http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(FilesListResponse{Paths: paths})
		return
	}

	pathParam := query.Get("path")
	clean, _ := cleanSandboxRelativePath(pathParam)
	info, err := root.Stat(clean)
	if err != nil {
		http.Error(w, `{"error": "file not found"}`, http.StatusNotFound)
		return
	}
	if info.IsDir() {
		http.Error(w, `{"error": "path is a directory"}`, http.StatusBadRequest)
		return
	}
	if info.Size() > maxFileContentBytes {
		http.Error(w, `{"error": "file content is too large"}`, http.StatusRequestEntityTooLarge)
		return
	}
	data, err := root.ReadFile(clean)
	if err != nil {
		http.Error(w, `{"error": "file not found"}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(FilesGetResponse{
		ContentBase64: base64.StdEncoding.EncodeToString(data),
		Size:          int64(len(data)),
	})
}

// listWorkspaceFiles returns the relative paths of regular files under prefix.
// It walks through os.Root so symlinks can never escape the task workspace.
func listWorkspaceFiles(root *os.Root, prefix string) ([]string, error) {
	clean := ""
	if prefix != "" {
		var err error
		clean, err = cleanSandboxRelativePath(prefix)
		if err != nil || strings.ContainsRune(prefix, 0) {
			return nil, fmt.Errorf("prefix must be relative and must not contain '..' or NUL")
		}
		clean = filepath.ToSlash(clean)
	}
	paths := make([]string, 0)
	err := fs.WalkDir(root.FS(), ".", func(name string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() || entry.Type()&fs.ModeSymlink != 0 {
			return nil
		}
		if clean != "" && name != clean && !strings.HasPrefix(name, clean+"/") {
			return nil
		}
		paths = append(paths, name)
		if len(paths) > servicePolicy.WorkspaceLimits.MaxFiles {
			return fmt.Errorf("workspace file limit exceeded")
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Strings(paths)
	return paths, nil
}

func workspaceWritebackHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}
	beginRequest()
	defer endRequest()
	body, err := readActivationRequestBody(r)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid writeback request: %v"}`, err), http.StatusBadRequest)
		return
	}
	var req workspace.WritebackRequest
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&req); err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid writeback request: %v"}`, err), http.StatusBadRequest)
		return
	}
	if err := workspace.ValidateIdentifier("workspace_id", req.WorkspaceID); err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err), http.StatusBadRequest)
		return
	}
	if err := workspace.ValidateIdentifier("task_id", req.TaskID); err != nil || req.BaseGeneration < 0 || req.FencingToken <= 0 {
		http.Error(w, `{"error": "invalid task/generation/fencing identity"}`, http.StatusBadRequest)
		return
	}
	if !authorizeActivationRequest(w, r, activationauth.ScopeWriteback, activationauth.Identity{
		WorkspaceID: req.WorkspaceID, TaskID: req.TaskID,
		Generation: req.BaseGeneration, FencingToken: req.FencingToken,
	}, activationauth.BodySHA256(body)) {
		return
	}
	workspaceDir, err := resolveExecutionWorkspace(req.WorkspaceID, req.TaskID)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err), http.StatusBadRequest)
		return
	}
	root, err := os.OpenRoot(workspaceDir)
	if err != nil {
		http.Error(w, `{"error": "task workspace is unavailable"}`, http.StatusConflict)
		return
	}
	defer root.Close()
	allowedHost, endpointErr := objectStoreEndpointHost()
	if endpointErr != nil {
		http.Error(w, `{"error": "object store endpoint is not configured"}`, http.StatusInternalServerError)
		return
	}
	client := &http.Client{
		Timeout: 10 * time.Minute,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return fmt.Errorf("workspace transfer redirects are forbidden")
		},
	}
	response := workspace.WritebackResponse{Receipts: make([]workspace.UploadReceipt, 0, len(req.Uploads))}
	for _, upload := range req.Uploads {
		clean, pathErr := workspace.NormalizeRelativePath(upload.RelativePath)
		if pathErr != nil {
			http.Error(w, `{"error": "invalid output path"}`, http.StatusBadRequest)
			return
		}
		if upload.Deleted {
			response.Receipts = append(response.Receipts, workspace.UploadReceipt{RelativePath: clean, Deleted: true})
			continue
		}
		parsed, parseErr := url.Parse(upload.URL)
		if parseErr != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
			http.Error(w, `{"error": "invalid signed output URL"}`, http.StatusBadRequest)
			return
		}
		if parsed.Host != allowedHost {
			http.Error(w, `{"error": "signed output URL host is not the configured object store"}`, http.StatusForbidden)
			return
		}
		file, openErr := root.Open(clean)
		if openErr != nil {
			http.Error(w, fmt.Sprintf(`{"error": "output %s is missing"}`, clean), http.StatusConflict)
			return
		}
		info, statErr := file.Stat()
		if statErr != nil || !info.Mode().IsRegular() || info.Size() != upload.Size {
			file.Close()
			http.Error(w, fmt.Sprintf(`{"error": "output %s size/type changed"}`, clean), http.StatusConflict)
			return
		}
		hasher := sha256.New()
		if _, hashErr := io.Copy(hasher, file); hashErr != nil || hex.EncodeToString(hasher.Sum(nil)) != upload.SHA256 {
			file.Close()
			http.Error(w, fmt.Sprintf(`{"error": "output %s checksum changed"}`, clean), http.StatusConflict)
			return
		}
		_, _ = file.Seek(0, io.SeekStart)
		putRequest, requestErr := http.NewRequestWithContext(r.Context(), http.MethodPut, parsed.String(), file)
		if requestErr != nil {
			file.Close()
			http.Error(w, `{"error": "failed to create output upload"}`, http.StatusInternalServerError)
			return
		}
		putRequest.ContentLength = upload.Size
		applyTransferHeaders(putRequest, upload.Headers)
		putResponse, uploadErr := client.Do(putRequest)
		file.Close()
		if uploadErr != nil {
			http.Error(w, fmt.Sprintf(`{"error": "output %s upload failed"}`, clean), http.StatusBadGateway)
			return
		}
		putResponse.Body.Close()
		if putResponse.StatusCode < 200 || putResponse.StatusCode >= 300 {
			http.Error(w, fmt.Sprintf(`{"error": "output %s upload returned status %d"}`, clean, putResponse.StatusCode), http.StatusBadGateway)
			return
		}
		response.Receipts = append(response.Receipts, workspace.UploadReceipt{RelativePath: clean, ObjectURI: upload.ObjectURI})
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(response)
}

func runtimeManifestHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}
	manifest, err := runtimeinfo.Load(runtimeinfo.PathFromEnv())
	if err != nil {
		http.Error(w, `{"error": "runtime manifest unavailable"}`, http.StatusServiceUnavailable)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(manifest)
}

// sandboxCommandCredential resolves the identity the untrusted command runs as.
// If the service is already unprivileged the command inherits that non-root
// identity (nil credential). If the service runs as root it MUST drop to a
// valid non-root uid/gid; it returns an error rather than falling back to root,
// because a root command could read PID1's environment (incl. the activation
// HMAC secret) and forge tokens for any workspace/task.
func sandboxCommandCredential() (*syscall.Credential, error) {
	return resolveCommandCredential(os.Geteuid(), os.Getenv("SANDBOX_COMMAND_UID"), os.Getenv("SANDBOX_COMMAND_GID"))
}

// resolveCommandCredential is the pure core of sandboxCommandCredential, split
// out so the fail-hard-as-root invariant is unit-testable without real euid.
func resolveCommandCredential(euid int, uidText, gidText string) (*syscall.Credential, error) {
	if euid != 0 {
		return nil, nil
	}
	uid, uidErr := strconv.ParseUint(uidText, 10, 32)
	gid, gidErr := strconv.ParseUint(gidText, 10, 32)
	if uidText == "" || gidText == "" || uidErr != nil || gidErr != nil || uid == 0 || gid == 0 {
		return nil, fmt.Errorf("refusing to run untrusted command as root: SANDBOX_COMMAND_UID and SANDBOX_COMMAND_GID must be set to a non-root uid/gid")
	}
	return &syscall.Credential{Uid: uint32(uid), Gid: uint32(gid)}, nil
}

func prepareTaskWorkspace(workspaceDir string, credential *syscall.Credential) error {
	if credential == nil {
		return nil
	}
	uid, err := checkedIntFromUint32(credential.Uid)
	if err != nil {
		return err
	}
	gid, err := checkedIntFromUint32(credential.Gid)
	if err != nil {
		return err
	}
	// Never recursively chown an agent-controlled tree: os.Chown follows
	// symlinks and would let a sandbox change ownership outside /workspace.
	// The workspace root is a control-plane-created directory, so changing it
	// through its already-open descriptor is sufficient. Newly created files
	// are chowned through their descriptors before they are exposed.
	dir, err := os.Open(workspaceDir)
	if err != nil {
		return err
	}
	defer dir.Close()
	info, err := dir.Stat()
	if err != nil {
		return err
	}
	if !info.IsDir() {
		return fmt.Errorf("task workspace root is not a directory")
	}
	return dir.Chown(uid, gid)
}

func prepareOwnedFile(file *os.File, credential *syscall.Credential, mode fs.FileMode) error {
	if file == nil || credential == nil {
		return nil
	}
	uid, err := checkedIntFromUint32(credential.Uid)
	if err != nil {
		return err
	}
	gid, err := checkedIntFromUint32(credential.Gid)
	if err != nil {
		return err
	}
	if err := file.Chown(uid, gid); err != nil {
		return err
	}
	return file.Chmod(mode)
}

// checkedIntFromUint32 converts a uid/gid to int, failing hard when the value
// exceeds the guaranteed signed-int range (int is 32-bit on 32-bit platforms)
// rather than silently wrapping to a negative id.
func checkedIntFromUint32(value uint32) (int, error) {
	if value > math.MaxInt32 {
		return 0, fmt.Errorf("uid/gid %d exceeds the 32-bit signed int range", value)
	}
	return int(value), nil
}

// objectStoreEndpointHost returns the host:port that presigned writeback URLs
// must target. It mirrors the endpoint the control plane presigns against
// (SANDBOX_WORKSPACE_S3_ENDPOINT, falling back to AWS_ENDPOINT_URL) and fails
// hard when unset so a misconfigured runner cannot relay control-plane URLs to
// an attacker-chosen host.
func objectStoreEndpointHost() (string, error) {
	endpoint := os.Getenv("SANDBOX_WORKSPACE_S3_ENDPOINT")
	if endpoint == "" {
		endpoint = os.Getenv("AWS_ENDPOINT_URL")
	}
	if endpoint == "" {
		return "", fmt.Errorf("object store endpoint is not configured: set SANDBOX_WORKSPACE_S3_ENDPOINT or AWS_ENDPOINT_URL")
	}
	parsed, err := url.Parse(strings.TrimRight(endpoint, "/"))
	if err != nil || parsed.Host == "" {
		return "", fmt.Errorf("object store endpoint is not a valid URL")
	}
	return parsed.Host, nil
}

func applyTransferHeaders(req *http.Request, headers map[string]string) {
	for key, value := range headers {
		if strings.EqualFold(key, "host") || strings.EqualFold(key, "content-length") {
			continue
		}
		req.Header.Set(key, value)
	}
}

// beginRequest/endRequest record activity for the idle watchdog.
func beginRequest() {
	lastRequestMu.Lock()
	lastRequest = time.Now()
	activeRequests++
	lastRequestMu.Unlock()
}

func endRequest() {
	lastRequestMu.Lock()
	if activeRequests > 0 {
		activeRequests--
	}
	lastRequest = time.Now()
	lastRequestMu.Unlock()
}

func loadActivationPolicy() (activationPolicy, error) {
	maxExecution, err := requiredPositiveIntEnv("MAX_EXECUTION_TIMEOUT_SECONDS")
	if err != nil {
		return activationPolicy{}, err
	}
	maxFiles, err := requiredPositiveIntEnv("SANDBOX_WORKSPACE_MAX_FILES")
	if err != nil {
		return activationPolicy{}, err
	}
	maxFileBytes, err := requiredPositiveInt64Env("SANDBOX_WORKSPACE_MAX_FILE_BYTES")
	if err != nil {
		return activationPolicy{}, err
	}
	maxBytes, err := requiredPositiveInt64Env("SANDBOX_WORKSPACE_MAX_BYTES")
	if err != nil {
		return activationPolicy{}, err
	}
	workspaceLimits := sandboxruntime.WorkspaceLimits{
		MaxFiles: maxFiles, MaxFileBytes: maxFileBytes, MaxBytes: maxBytes,
	}
	if err := workspaceLimits.Validate(); err != nil {
		return activationPolicy{}, fmt.Errorf("sandbox workspace limits are invalid: %w", err)
	}
	idleRaw := os.Getenv("IDLE_TIMEOUT_SECONDS")
	if idleRaw == "" {
		return activationPolicy{}, fmt.Errorf("IDLE_TIMEOUT_SECONDS is required; use 0 to disable")
	}
	idleSeconds, err := strconv.Atoi(idleRaw)
	if err != nil || idleSeconds < 0 {
		return activationPolicy{}, fmt.Errorf("IDLE_TIMEOUT_SECONDS must be a non-negative integer")
	}
	return activationPolicy{
		MaxExecutionTimeoutSeconds: maxExecution,
		IdleTimeout:                time.Duration(idleSeconds) * time.Second,
		WorkspaceLimits:            workspaceLimits,
	}, nil
}

func requiredPositiveIntEnv(name string) (int, error) {
	raw := os.Getenv(name)
	value, err := strconv.Atoi(raw)
	if raw == "" || err != nil || value <= 0 {
		return 0, fmt.Errorf("%s must be a positive integer", name)
	}
	return value, nil
}

func requiredPositiveInt64Env(name string) (int64, error) {
	raw := os.Getenv(name)
	value, err := strconv.ParseInt(raw, 10, 64)
	if raw == "" || err != nil || value <= 0 {
		return 0, fmt.Errorf("%s must be a positive integer", name)
	}
	return value, nil
}

// startIdleWatchdog launches a goroutine that exits the process when no
// /execute or /activate request has arrived for IDLE_TIMEOUT_SECONDS. This
// bounds the lifetime of an unused activation process. Task state is safe to
// discard because the canonical workspace is stored in object storage.
// Disabled when IDLE_TIMEOUT_SECONDS=0 or unset.
func startIdleWatchdog(timeout time.Duration) {
	if timeout == 0 {
		return
	}
	logger.Info("idle watchdog enabled", "timeout_seconds", int(timeout.Seconds()))

	go func() {
		check := time.NewTicker(30 * time.Second)
		defer check.Stop()
		for range check.C {
			lastRequestMu.Lock()
			idle := time.Since(lastRequest)
			active := activeRequests
			lastRequestMu.Unlock()
			if active == 0 && idle >= timeout {
				logger.Info("idle timeout reached, exiting", "idle_seconds", int(idle.Seconds()))
				os.Exit(0)
			}
		}
	}()
}

var errWorkspaceQuotaExceeded = errors.New("workspace quota exceeded")

func enforceWorkspaceLimits(workspaceDir string, limits sandboxruntime.WorkspaceLimits) error {
	return enforceWorkspaceLimitsContext(context.Background(), workspaceDir, limits)
}

func enforceWorkspaceLimitsContext(ctx context.Context, workspaceDir string, limits sandboxruntime.WorkspaceLimits) error {
	_, err := measureWorkspaceUsageContext(ctx, workspaceDir, limits)
	return err
}

// measureWorkspaceUsage does not follow symlinks. Every non-root entry counts
// against MaxFiles, including directories and symlinks, because each consumes
// a host inode even when it contributes few or no content bytes.
func measureWorkspaceUsage(workspaceDir string, limits sandboxruntime.WorkspaceLimits) (sandboxruntime.WorkspaceUsage, error) {
	return measureWorkspaceUsageContext(context.Background(), workspaceDir, limits)
}

func measureWorkspaceUsageContext(ctx context.Context, workspaceDir string, limits sandboxruntime.WorkspaceLimits) (sandboxruntime.WorkspaceUsage, error) {
	if err := limits.Validate(); err != nil {
		return sandboxruntime.WorkspaceUsage{}, fmt.Errorf("workspace policy is unavailable: %w", err)
	}
	root := filepath.Clean(workspaceDir)
	usage := sandboxruntime.WorkspaceUsage{}
	err := filepath.WalkDir(root, func(current string, entry os.DirEntry, walkErr error) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		if walkErr != nil {
			return walkErr
		}
		if current == root {
			return nil
		}
		usage.Entries++
		if !entry.IsDir() {
			info, err := entry.Info()
			if err != nil {
				return err
			}
			size := info.Size()
			if size < 0 || usage.TotalBytes > int64(^uint64(0)>>1)-size {
				return fmt.Errorf("workspace usage overflowed")
			}
			usage.TotalBytes += size
			if size > usage.LargestBytes {
				usage.LargestBytes = size
			}
		}
		if err := usage.Enforce(limits); err != nil {
			return fmt.Errorf("%w: %v", errWorkspaceQuotaExceeded, err)
		}
		return nil
	})
	return usage, err
}

func copyWithContext(ctx context.Context, destination io.Writer, source io.Reader) (int64, error) {
	buffer := make([]byte, 32*1024)
	var total int64
	for {
		if err := ctx.Err(); err != nil {
			return total, err
		}
		read, readErr := source.Read(buffer)
		if read > 0 {
			written, writeErr := destination.Write(buffer[:read])
			total += int64(written)
			if writeErr != nil {
				return total, writeErr
			}
			if written != read {
				return total, io.ErrShortWrite
			}
		}
		if errors.Is(readErr, io.EOF) {
			return total, nil
		}
		if readErr != nil {
			return total, readErr
		}
	}
}

// rejectUnsafeWorkspace is shared by command and file mutation paths. Once a
// live workspace is over policy (or cannot be audited), keeping it would let a
// later request continue from untrusted state. Durable inputs remain in object
// storage and are rehydrated into a fresh sandbox on the next demand.
func rejectUnsafeWorkspace(w http.ResponseWriter, workspaceDir string, auditErr error) {
	w.Header().Set("X-Agentarea-Executor-Unsafe", "true")
	w.Header().Set("Connection", "close")
	defer executorInvalidator()
	if err := os.RemoveAll(workspaceDir); err != nil {
		logger.Error("discard unsafe workspace", "workspace", workspaceDir, "audit_error", auditErr, "cleanup_error", err)
		http.Error(w, `{"error": "workspace audit failed and cleanup failed"}`, http.StatusInternalServerError)
		return
	}
	if errors.Is(auditErr, errWorkspaceQuotaExceeded) {
		http.Error(w, `{"error": "workspace quota exceeded; ephemeral workspace discarded"}`, http.StatusInsufficientStorage)
		return
	}
	logger.Error("workspace audit failed", "workspace", workspaceDir, "error", auditErr)
	http.Error(w, `{"error": "workspace audit failed; ephemeral workspace discarded"}`, http.StatusInternalServerError)
}

func ensureWorkspaceFileSlot(root *os.Root, workspaceDir, target string) error {
	if _, err := root.Stat(target); err == nil {
		return nil
	} else if !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	usage, err := measureWorkspaceUsage(workspaceDir, servicePolicy.WorkspaceLimits)
	if err != nil {
		return err
	}
	if usage.Entries >= servicePolicy.WorkspaceLimits.MaxFiles {
		return fmt.Errorf("%w: sandbox workspace holds %d filesystem entries; policy allows %d", errWorkspaceQuotaExceeded, usage.Entries, servicePolicy.WorkspaceLimits.MaxFiles)
	}
	return nil
}

func resolveExecutionWorkspace(workspaceID, taskID string) (string, error) {
	dir, err := executionWorkspacePath(workspaceID, taskID)
	if err != nil {
		return "", err
	}
	workspacesRoot := filepath.Join(workspaceRoot, "workspaces")
	workspaceDir := filepath.Join(workspacesRoot, workspaceID)
	tasksRoot := filepath.Join(workspaceDir, "tasks")
	if err := os.MkdirAll(tasksRoot, 0o711); err != nil {
		return "", fmt.Errorf("failed to create task workspace root: %w", err)
	}
	// The activation service creates this parent as root, then drops task
	// commands to the sandbox uid. Permit traversal without permitting task
	// directory listing; each task directory remains private at 0700.
	for _, parent := range []string{workspacesRoot, workspaceDir, tasksRoot} {
		if err := os.Chmod(parent, 0o711); err != nil {
			return "", fmt.Errorf("failed to prepare task workspace root: %w", err)
		}
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", fmt.Errorf("failed to create task workspace: %w", err)
	}
	return dir, nil
}

func executionWorkspacePath(workspaceID, taskID string) (string, error) {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return "", err
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return "", err
	}
	dir := filepath.Join(workspaceRoot, "workspaces", workspaceID, "tasks", taskID)
	if err := ValidateFilePath(workspaceRoot, dir); err != nil {
		return "", err
	}
	return dir, nil
}

func existingExecutionWorkspace(workspaceID, taskID string) (string, error) {
	dir, err := executionWorkspacePath(workspaceID, taskID)
	if err != nil {
		return "", err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return "", err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", fmt.Errorf("task workspace is not a directory")
	}
	return dir, nil
}

func readActivationRequestBody(r *http.Request) ([]byte, error) {
	body, err := io.ReadAll(io.LimitReader(r.Body, maxActivationRequestBytes+1))
	if err != nil {
		return nil, fmt.Errorf("read request body: %w", err)
	}
	if len(body) > maxActivationRequestBytes {
		return nil, fmt.Errorf("request body exceeds %d bytes", maxActivationRequestBytes)
	}
	return body, nil
}

func authorizeActivationRequest(w http.ResponseWriter, r *http.Request, scope string, identity activationauth.Identity, bodySHA256 string) bool {
	token, err := activationauth.BearerToken(r.Header.Get("Authorization"))
	if err == nil {
		err = activationauth.VerifyFromEnv(token, scope, identity, bodySHA256, time.Now())
	}
	if err != nil {
		http.Error(w, `{"error": "unauthorized"}`, http.StatusUnauthorized)
		return false
	}
	return true
}

func waitForReady(timeout time.Duration, port int, path string) error {
	start := time.Now()
	address := fmt.Sprintf("localhost:%d", port)

	for time.Since(start) < timeout {
		if path != "" {
			// HTTP health check against localhost only.
			// Construct via url.URL so the host is always the validated
			// localhost:<port> address and the path is treated as a URL
			// path component, not a raw string — preventing SSRF.
			healthURL := &url.URL{
				Scheme: "http",
				Host:   address,
				Path:   path,
			}
			resp, err := http.Get(healthURL.String())
			if err == nil {
				resp.Body.Close()
				if resp.StatusCode == http.StatusOK {
					return nil
				}
			}
		} else {
			// TCP connect check
			conn, err := net.DialTimeout("tcp", address, time.Second)
			if err == nil {
				conn.Close()
				return nil
			}
		}
		time.Sleep(100 * time.Millisecond)
	}

	return fmt.Errorf("timeout waiting for ready")
}
