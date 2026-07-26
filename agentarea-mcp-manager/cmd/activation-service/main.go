// Activation service runs inside warm pods
// Handles on-demand MCP activation via HTTP API
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"math"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/workspace"
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
)

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

	http.HandleFunc("/health", healthHandler)
	http.HandleFunc("/activate", activateHandler)
	http.HandleFunc("/execute", executeHandler)
	http.HandleFunc("/files", filesHandler)
	http.HandleFunc("/workspace/writeback", workspaceWritebackHandler)
	http.HandleFunc("/runtime/manifest", runtimeManifestHandler)

	port := os.Getenv("ACTIVATION_PORT")
	if port == "" {
		port = "8080"
	}

	startIdleWatchdog()

	// Security: Configure server with timeouts to prevent Slowloris attacks
	server := &http.Server{
		Addr:         ":" + port,
		Handler:      nil,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: time.Duration(maxExecutionTimeoutSeconds()+30) * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	logger.Info("Listening", "port", port)
	if err := server.ListenAndServe(); err != nil {
		logger.Error("Server failed", "error", err)
		os.Exit(1)
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	response := map[string]string{
		"status": status,
	}
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(response); err != nil {
		logger.Error("Failed to encode response", "error", err)
	}
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

		if data, err := os.ReadFile(configSource); err == nil {
			if err := os.WriteFile(configDest, data, 0600); err != nil {
				logger.Warn("Failed to copy config.json", "error", err)
			}
		}
	}

	// Extract layers in order to create rootfs
	for _, layerPath := range manifest[0].Layers {
		// Security: Validate layer path
		if err := ValidateLayerPath(layerPath); err != nil {
			logger.Warn("Skipping invalid layer path", "layer", layerPath, "error", err)
			continue
		}

		fullPath := filepath.Join(tempDir, layerPath)
		// Re-validate the joined path
		if err := ValidateFilePath(tempDir, fullPath); err != nil {
			logger.Warn("Layer path escapes temp directory", "layer", layerPath)
			continue
		}

		cmd, err := SafeCommand("tar", "-xf", fullPath, "-C", extractDir)
		if err != nil {
			logger.Warn("Invalid tar command", "error", err)
			continue
		}
		if err := cmd.Run(); err != nil {
			logger.Warn("Failed to extract layer", "layer", layerPath, "error", err)
			// Continue with other layers
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
		// Chroot is unavailable (e.g. Kata Containers VM environment where the VM
		// boundary provides isolation instead of chroot). Fall back to direct execution.
		// args[0] originates from the hash-verified image config, not the HTTP request.
		logger.Warn("Chroot unavailable, falling back to direct execution (VM isolation expected)", "error", err)

		cmd, err = SafeCommand(args[0], args[1:]...)
		if err != nil {
			return fmt.Errorf("invalid command: %w", err)
		}
		cmd.Dir = hostWorkDir
		cmd.Env = append(env, buildPathEnv(rootDir)...)
		cmd.SysProcAttr = &syscall.SysProcAttr{
			Setpgid: true,
		}
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr

		if err := cmd.Start(); err != nil {
			return fmt.Errorf("failed to start process: %w", err)
		}
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

func buildPathEnv(rootDir string) []string {
	paths := []string{
		filepath.Join(rootDir, "usr/local/sbin"),
		filepath.Join(rootDir, "usr/local/bin"),
		filepath.Join(rootDir, "usr/sbin"),
		filepath.Join(rootDir, "usr/bin"),
		filepath.Join(rootDir, "sbin"),
		filepath.Join(rootDir, "bin"),
	}
	if existingPath := os.Getenv("PATH"); existingPath != "" {
		paths = append(paths, existingPath)
	}
	return []string{"PATH=" + strings.Join(paths, ":")}
}

const (
	defaultOutputCaptureBytes int64 = 1024 * 1024
	maxOutputCaptureBytes     int64 = 16 * 1024 * 1024
)

// ExecuteRequest represents a manifest-backed command execution request.
//
// TaskID and WorkspaceManifestRef identify the canonical task workspace.
// Each request rehydrates the referenced immutable manifest before executing;
// local pod state is only a cache and is never authoritative.
type ExecuteRequest struct {
	CommandBody          string                 `json:"command_body,omitempty"`
	CommandPath          string                 `json:"command_path,omitempty"`
	PackageInstall       string                 `json:"package_install"`
	ArtifactPaths        []string               `json:"artifact_paths,omitempty"`
	InputRefs            []InputRef             `json:"input_refs,omitempty"`
	TimeoutSeconds       int                    `json:"timeout_seconds,omitempty"`
	StdoutMaxBytes       int64                  `json:"stdout_max_bytes,omitempty"`
	StderrMaxBytes       int64                  `json:"stderr_max_bytes,omitempty"`
	WorkflowID           string                 `json:"workflow_id,omitempty"`
	TaskID               string                 `json:"task_id,omitempty"`
	WorkspaceID          string                 `json:"workspace_id,omitempty"`
	WorkspaceManifestRef *workspace.ManifestRef `json:"workspace_manifest_ref,omitempty"`
	WorkspaceHydration   *workspace.Hydration   `json:"workspace_hydration,omitempty"`
}

// InputRef is a durable task input to materialize into the session workspace at
// first bring-up. URL is a short-lived presigned GET; the executor fetches it
// over the same host-allowlisted transport write-back uses and holds no
// object-store credentials of its own.
type InputRef struct {
	RelativePath string `json:"relative_path"`
	URL          string `json:"url"`
	ObjectURI    string `json:"object_uri,omitempty"`
	SHA256       string `json:"sha256,omitempty"`
	Size         int64  `json:"size,omitempty"`
}

const maxCommandBodyBytes = 256 * 1024

// maxInputRefs bounds how many durable inputs one bring-up may materialize.
const maxInputRefs = 200

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
	if err := runtimeinfo.ValidatePackageInstall(req.PackageInstall); err != nil {
		http.Error(w, `{"error": "package_install must be allowed or locked"}`, http.StatusBadRequest)
		return
	}
	runtimeManifest, err := runtimeinfo.Load(runtimeinfo.PathFromEnv())
	if err != nil {
		http.Error(w, `{"error": "runtime manifest unavailable"}`, http.StatusServiceUnavailable)
		return
	}
	if !runtimeManifest.SupportsPackageInstall(req.PackageInstall) {
		http.Error(
			w,
			fmt.Sprintf(
				`{"error": "runtime_profile_unavailable", "package_install": %q, "managed_environment": %q}`,
				req.PackageInstall,
				runtimeManifest.ManagedEnvironment,
			),
			http.StatusConflict,
		)
		return
	}

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

	timeout := 30
	maxTimeout := maxExecutionTimeoutSeconds()
	if req.TimeoutSeconds > 0 && req.TimeoutSeconds <= maxTimeout {
		timeout = req.TimeoutSeconds
	}

	workspaceDir, provisionStatus, provisionErr := resolveExecutionWorkspaceWithInputs(req.TaskID, req.InputRefs)
	if provisionErr != "" {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, provisionErr), provisionStatus)
		return
	}
	commandsDir := filepath.Join(workspaceDir, ".agentarea", "commands")
	if err := os.MkdirAll(commandsDir, 0o700); err != nil {
		http.Error(w, `{"error": "failed to prepare command directory"}`, http.StatusInternalServerError)
		return
	}
	commandFile := filepath.Join(commandsDir, "command.sh")
	if err := os.WriteFile(commandFile, []byte(req.CommandBody), 0o700); err != nil {
		http.Error(w, `{"error": "failed to write command"}`, http.StatusInternalServerError)
		return
	}
	cmd := exec.Command("sh", commandFile) // #nosec G204 -- interpreter is constant; commandFile is a fixed path inside the isolated per-task workspace
	cmd.Dir = workspaceDir
	// Resolve the non-root identity to run the untrusted command as. When the
	// service runs as root this MUST succeed; running untrusted code as root
	// would expose PID1's environment (incl. the activation secret) via /proc.
	credential, err := sandboxCommandCredential()
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusInternalServerError)
		return
	}
	if err := prepareTaskWorkspace(workspaceDir, credential); err != nil {
		http.Error(w, `{"error": "failed to prepare non-root task workspace"}`, http.StatusInternalServerError)
		return
	}

	cmd.Env = sandboxExecutionEnvironment(req.WorkspaceID, req.TaskID, workspaceDir)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Credential: credential}

	// Capture output
	stdout := newBoundedBuffer(stdoutLimit)
	stderr := newBoundedBuffer(stderrLimit)
	cmd.Stdout = stdout
	cmd.Stderr = stderr

	start := time.Now()
	artifactSince := start

	// Run with timeout
	if err := cmd.Start(); err != nil {
		_, _ = fmt.Fprintf(stderr, "failed to start: %v", err)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(ExecuteResponse{
			Stderr:          stderr.String(),
			StderrTruncated: stderr.Truncated(),
			ExitCode:        1,
			ExecutionTimeMs: time.Since(start).Milliseconds(),
		})
		return
	}

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()

	select {
	case err := <-done:
		elapsed := time.Since(start).Milliseconds()
		exitCode := 0
		if err != nil {
			if exitErr, ok := err.(*exec.ExitError); ok {
				exitCode = exitErr.ExitCode()
			} else {
				exitCode = 1
			}
		}
		changes, changesErr := collectWorkspaceChanges(workspaceDir, req.WorkspaceHydration)
		if changesErr != nil {
			http.Error(w, `{"error": "failed to describe workspace changes"}`, http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(ExecuteResponse{
			Stdout:           stdout.String(),
			Stderr:           stderr.String(),
			StdoutTruncated:  stdout.Truncated(),
			StderrTruncated:  stderr.Truncated(),
			ExitCode:         exitCode,
			ExecutionTimeMs:  elapsed,
			Artifacts:        collectArtifacts(workspaceDir, req.ArtifactPaths, artifactSince),
			WorkspaceChanges: changes,
		})

	case <-time.After(time.Duration(timeout) * time.Second):
		killProcessGroup(cmd.Process)
		<-done
		if stderr.Len() > 0 {
			_, _ = stderr.Write([]byte("\n"))
		}
		_, _ = stderr.Write([]byte("execution timed out"))
		changes, changesErr := collectWorkspaceChanges(workspaceDir, req.WorkspaceHydration)
		if changesErr != nil {
			http.Error(w, `{"error": "failed to describe workspace changes"}`, http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(ExecuteResponse{
			Stdout:           stdout.String(),
			Stderr:           stderr.String(),
			StdoutTruncated:  stdout.Truncated(),
			StderrTruncated:  stderr.Truncated(),
			ExitCode:         137,
			ExecutionTimeMs:  time.Since(start).Milliseconds(),
			Artifacts:        collectArtifacts(workspaceDir, req.ArtifactPaths, artifactSince),
			WorkspaceChanges: changes,
		})
	}

	logger.Info("Script executed",
		"task_id", req.TaskID,
		"stdout_bytes", stdout.Len(),
		"elapsed_ms", time.Since(start).Milliseconds(),
	)
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
			return nil, fmt.Errorf("unsupported_contract_version: inline commands and files are forbidden; use command_path and workspace_manifest_ref")
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

func collectArtifacts(workspace string, paths []string, since time.Time) []SandboxArtifact {
	if len(paths) == 0 {
		paths = discoverAutoArtifacts(workspace, since)
	}
	if len(paths) == 0 {
		return nil
	}

	root, err := os.OpenRoot(workspace)
	if err != nil {
		return []SandboxArtifact{{Error: fmt.Sprintf("failed to open workspace root: %s", err)}}
	}
	defer root.Close()

	artifacts := make([]SandboxArtifact, 0, len(paths))
	for _, requested := range paths {
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
		_, hashErr := io.Copy(hasher, file)
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

	return artifacts
}

func collectWorkspaceChanges(workspaceDir string, hydration *workspace.Hydration) ([]workspace.ChangeDescriptor, error) {
	if hydration == nil {
		return nil, nil
	}
	baseline := make(map[string]workspace.Download, len(hydration.Downloads))
	for _, entry := range hydration.Downloads {
		baseline[entry.RelativePath] = entry
	}
	changes := make([]workspace.ChangeDescriptor, 0)
	err := filepath.WalkDir(workspaceDir, func(localPath string, entry os.DirEntry, walkErr error) error {
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
		_, err = io.Copy(hasher, file)
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

// maxFileContentBytes bounds a single file transferred through the sandbox file
// API. It mirrors the output-capture ceiling so a stale or hostile client cannot
// exhaust the pod's emptyDir with one request.
const maxFileContentBytes = 16 * 1024 * 1024

// FilesPutRequest writes a single file into the per-task workspace on the same
// filesystem bash executes against, so the agent's file tool and its shell see
// one workspace.
type FilesPutRequest struct {
	WorkspaceID   string `json:"workspace_id"`
	TaskID        string `json:"task_id"`
	Path          string `json:"path"`
	ContentBase64 string `json:"content_base64"`
}

// FilesPutResponse acknowledges a written file.
type FilesPutResponse struct {
	Path string `json:"path"`
	Size int    `json:"size"`
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
	// Resolve the non-root identity before writing. When the service runs as
	// root the file MUST end up owned by the sandbox uid, otherwise the bash
	// command (which runs as that uid) could not read or overwrite it.
	credential, err := sandboxCommandCredential()
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusInternalServerError)
		return
	}
	workspaceDir, err := resolveExecutionWorkspace(req.TaskID)
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
	if err := prepareTaskWorkspace(workspaceDir, credential); err != nil {
		http.Error(w, `{"error": "failed to prepare non-root task workspace"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(FilesPutResponse{Path: clean, Size: len(content)})
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
	if workspaceID == "" || taskID == "" {
		http.Error(w, `{"error": "workspace_id and task_id are required"}`, http.StatusBadRequest)
		return
	}
	if !authorizeActivationRequest(w, r, activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(body)) {
		return
	}
	workspaceDir, err := resolveExecutionWorkspace(taskID)
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
	clean, err := cleanSandboxRelativePath(pathParam)
	if err != nil || strings.ContainsRune(pathParam, 0) {
		http.Error(w, `{"error": "path must be relative and must not contain '..' or NUL"}`, http.StatusBadRequest)
		return
	}
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
	workspaceDir, err := resolveExecutionWorkspace(req.TaskID)
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
	packageInstall := r.URL.Query().Get("package_install")
	if packageInstall == "" {
		packageInstall = runtimeinfo.PackageInstallAllowed
	}
	if err := runtimeinfo.ValidatePackageInstall(packageInstall); err != nil {
		http.Error(w, `{"error": "package_install must be allowed or locked"}`, http.StatusBadRequest)
		return
	}
	manifest, err := runtimeinfo.Load(runtimeinfo.PathFromEnv())
	if err != nil {
		http.Error(w, `{"error": "runtime manifest unavailable"}`, http.StatusServiceUnavailable)
		return
	}
	if !manifest.SupportsPackageInstall(packageInstall) {
		http.Error(w, `{"error": "runtime_profile_unavailable"}`, http.StatusConflict)
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
	return filepath.WalkDir(workspaceDir, func(path string, _ os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		return os.Chown(path, uid, gid)
	})
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

// objectStoreBucket returns the bucket a task input's object_uri must belong to.
// It mirrors the control plane's bucket resolution (SANDBOX_WORKSPACE_S3_BUCKET,
// then ARTIFACTS_BUCKET_NAME) and fails hard when unset so an input cannot be
// sourced from an unverifiable bucket.
func objectStoreBucket() (string, error) {
	bucket := os.Getenv("SANDBOX_WORKSPACE_S3_BUCKET")
	if bucket == "" {
		bucket = os.Getenv("ARTIFACTS_BUCKET_NAME")
	}
	if bucket == "" {
		return "", fmt.Errorf("object store bucket is not configured: set SANDBOX_WORKSPACE_S3_BUCKET or ARTIFACTS_BUCKET_NAME")
	}
	return bucket, nil
}

// resolveExecutionWorkspaceWithInputs resolves the task's session workspace and
// materializes its durable inputs into it before the command runs. It returns
// the HTTP status and message to send on failure so executeHandler keeps a
// single workspace error path. A bad task identity is a client error; an input
// transfer failure is an internal error surfaced loudly, never swallowed.
func resolveExecutionWorkspaceWithInputs(taskID string, refs []InputRef) (string, int, string) {
	workspaceDir, err := resolveExecutionWorkspace(taskID)
	if err != nil {
		return "", http.StatusBadRequest, err.Error()
	}
	// Provision before prepareTaskWorkspace so the existing chown hands the
	// inputs to the sandbox uid alongside the command.
	if err := provisionTaskInputs(workspaceDir, refs); err != nil {
		return "", http.StatusInternalServerError, err.Error()
	}
	return workspaceDir, 0, ""
}

// provisionTaskInputs materializes a task's durable inputs into the session
// workspace on the first bring-up of a session, so bash sees them as ordinary
// files in its one working directory. It is the mirror of copy-out and, like the
// write-back upload, transfers over a presigned URL and holds no object-store
// credentials. A marker file makes it run once per session: the persistent
// workspace already holds the inputs on every later call.
func provisionTaskInputs(workspaceDir string, refs []InputRef) error {
	if len(refs) == 0 {
		return nil
	}
	marker := filepath.Join(workspaceDir, ".agentarea", ".inputs_provisioned")
	if _, err := os.Stat(marker); err == nil {
		return nil
	} else if !os.IsNotExist(err) {
		return fmt.Errorf("inspect inputs marker: %w", err)
	}
	if len(refs) > maxInputRefs {
		return fmt.Errorf("input_refs exceeds %d entries", maxInputRefs)
	}
	allowedHost, err := objectStoreEndpointHost()
	if err != nil {
		return err
	}
	bucket, err := objectStoreBucket()
	if err != nil {
		return err
	}
	client := &http.Client{
		Timeout: 10 * time.Minute,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return fmt.Errorf("workspace transfer redirects are forbidden")
		},
	}
	for _, ref := range refs {
		if err := fetchTaskInput(client, workspaceDir, allowedHost, bucket, ref); err != nil {
			return err
		}
	}
	if err := os.MkdirAll(filepath.Dir(marker), 0o700); err != nil {
		return fmt.Errorf("create inputs marker directory: %w", err)
	}
	if err := os.WriteFile(marker, []byte(time.Now().UTC().Format(time.RFC3339)), 0o600); err != nil {
		return fmt.Errorf("write inputs marker: %w", err)
	}
	return nil
}

// fetchTaskInput downloads one durable input from its presigned URL and writes
// it into the workspace at its relative path. Every failure is returned, never
// swallowed: a missing input the agent expects must surface loudly.
func fetchTaskInput(client *http.Client, workspaceDir, allowedHost, bucket string, ref InputRef) error {
	clean, err := workspace.NormalizeRelativePath(ref.RelativePath)
	if err != nil {
		return fmt.Errorf("invalid input path %q", ref.RelativePath)
	}
	if err := validateInputObjectURI(ref.ObjectURI, bucket); err != nil {
		return err
	}
	parsed, err := url.Parse(ref.URL)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		return fmt.Errorf("invalid signed input URL for %q", clean)
	}
	if parsed.Host != allowedHost {
		return fmt.Errorf("signed input URL host is not the configured object store for %q", clean)
	}
	target := filepath.Join(workspaceDir, filepath.FromSlash(clean))
	if err := ValidateFilePath(workspaceDir, target); err != nil {
		return err
	}
	request, err := http.NewRequest(http.MethodGet, parsed.String(), nil)
	if err != nil {
		return fmt.Errorf("create input download for %q: %w", clean, err)
	}
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("download input %q: %w", clean, err)
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("download input %q returned status %d", clean, response.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxFileContentBytes+1))
	if err != nil {
		return fmt.Errorf("read input %q: %w", clean, err)
	}
	if int64(len(body)) > maxFileContentBytes {
		return fmt.Errorf("input %q exceeds %d bytes", clean, maxFileContentBytes)
	}
	if ref.Size != 0 && int64(len(body)) != ref.Size {
		return fmt.Errorf("input %q size mismatch: got %d, want %d", clean, len(body), ref.Size)
	}
	if ref.SHA256 != "" {
		sum := sha256.Sum256(body)
		if hex.EncodeToString(sum[:]) != ref.SHA256 {
			return fmt.Errorf("input %q checksum mismatch", clean)
		}
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
		return fmt.Errorf("create input directory for %q: %w", clean, err)
	}
	if err := os.WriteFile(target, body, 0o600); err != nil {
		return fmt.Errorf("write input %q: %w", clean, err)
	}
	return nil
}

// validateInputObjectURI rejects any input whose object_uri is not a well-formed
// immutable s3 URI under the configured bucket, mirroring the write-back host
// allowlist so a task cannot be fed an object from an unauthorized bucket.
func validateInputObjectURI(objectURI, bucket string) error {
	parsed, err := url.Parse(objectURI)
	if err != nil || parsed.Scheme != "s3" || parsed.Host == "" || parsed.Path == "" || parsed.RawQuery != "" || parsed.Fragment != "" {
		return fmt.Errorf("input object_uri must be an immutable s3 URI")
	}
	if parsed.Host != bucket {
		return fmt.Errorf("input object_uri bucket %q is not the configured object store", parsed.Host)
	}
	return nil
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

func maxExecutionTimeoutSeconds() int {
	raw := os.Getenv("MAX_EXECUTION_TIMEOUT_SECONDS")
	if raw == "" {
		return 1800
	}
	timeoutSec, err := strconv.Atoi(raw)
	if err != nil || timeoutSec <= 0 {
		logger.Warn("invalid MAX_EXECUTION_TIMEOUT_SECONDS, using default", "value", raw)
		return 1800
	}
	return timeoutSec
}

func killProcessGroup(process *os.Process) {
	if process == nil {
		return
	}
	if err := syscall.Kill(-process.Pid, syscall.SIGKILL); err == nil {
		return
	}
	_ = process.Kill()
}

// startIdleWatchdog launches a goroutine that exits the process when no
// /execute or /activate request has arrived for IDLE_TIMEOUT_SECONDS. This
// bounds the lifetime of an unused activation process. Task state is safe to
// discard because the canonical workspace is stored in object storage.
// Disabled when IDLE_TIMEOUT_SECONDS=0 or unset.
func startIdleWatchdog() {
	raw := os.Getenv("IDLE_TIMEOUT_SECONDS")
	if raw == "" {
		return
	}
	timeoutSec, err := strconv.Atoi(raw)
	if err != nil || timeoutSec <= 0 {
		logger.Warn("invalid IDLE_TIMEOUT_SECONDS, watchdog disabled", "value", raw)
		return
	}
	timeout := time.Duration(timeoutSec) * time.Second
	logger.Info("idle watchdog enabled", "timeout_seconds", timeoutSec)

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

func resolveExecutionWorkspace(taskID string) (string, error) {
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return "", err
	}
	tasksRoot := filepath.Join(workspaceRoot, "tasks")
	if err := os.MkdirAll(tasksRoot, 0o711); err != nil {
		return "", fmt.Errorf("failed to create task workspace root: %w", err)
	}
	// The activation service creates this parent as root, then drops task
	// commands to the sandbox uid. Permit traversal without permitting task
	// directory listing; each task directory remains private at 0700.
	if err := os.Chmod(tasksRoot, 0o711); err != nil {
		return "", fmt.Errorf("failed to prepare task workspace root: %w", err)
	}
	dir := filepath.Join(tasksRoot, taskID)
	if err := ValidateFilePath(workspaceRoot, dir); err != nil {
		return "", err
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", fmt.Errorf("failed to create task workspace: %w", err)
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
