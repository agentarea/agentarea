// Activation service runs inside warm pods
// Handles on-demand MCP activation via HTTP API
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

var (
	status     = "waiting"
	mcpProcess *os.Process
	logger     *slog.Logger

	// lastRequestTime tracks the wall-clock time of the most recent /execute
	// or /activate call. The idle-timeout watchdog reads this to decide when
	// to self-exit, which lets K8s reclaim the pod if mcp-manager never
	// issues an explicit DELETE (worker crash, network partition, etc.).
	lastRequestMu sync.Mutex
	lastRequest   = time.Now()
)

// workspaceRoot is the parent directory for all per-workflow workspaces.
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
	http.HandleFunc("/workspace/cleanup", workspaceCleanupHandler)

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
		WriteTimeout: 30 * time.Second,
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
	start := time.Now()

	if status != "waiting" {
		http.Error(w, `{"error": "pod already assigned"}`, http.StatusConflict)
		return
	}

	var req ActivateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
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
	if err := startContainer(extractDir, entrypoint, command, env); err != nil {
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
	if !(name[0] >= 'A' && name[0] <= 'Z') && !(name[0] >= 'a' && name[0] <= 'z') && name[0] != '_' {
		return false
	}
	// Can contain letters, digits, and underscores
	for i := 1; i < len(name); i++ {
		c := name[i]
		if !(c >= 'A' && c <= 'Z') && !(c >= 'a' && c <= 'z') && !(c >= '0' && c <= '9') && c != '_' {
			return false
		}
	}
	return true
}

func startContainer(rootDir string, entrypoint, command []string, env []string) error {
	// Combine entrypoint and command
	args := append(entrypoint, command...)
	if len(args) == 0 {
		return fmt.Errorf("no command to execute")
	}

	logger.Info("Starting container",
		"executable", args[0],
		"args", args[1:],
	)

	// Security: Validate the executable path
	if err := SanitizeCommandArg(args[0]); err != nil {
		return fmt.Errorf("invalid executable: %w", err)
	}

	// Try chroot first (requires CAP_SYS_CHROOT)
	cmd, err := SafeCommand("chroot", append([]string{rootDir}, args...)...)
	if err != nil {
		return fmt.Errorf("invalid chroot command: %w", err)
	}
	cmd.Env = env
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
		cmd.Dir = rootDir
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

// ExecuteRequest represents a script execution request.
//
// Workspace lifetime depends on WorkflowID:
//   - empty: a fresh tempdir is created and removed after the call.
//   - set:   /workspace/wf-<WorkflowID>/ is created if missing, persisted across
//            calls with the same WorkflowID, and removed only when the pod is
//            torn down (deleted by mcp-manager) or the idle-timeout backstop
//            fires. Files, installed packages, and any state written here
//            survive between bash calls in the same workflow.
type ExecuteRequest struct {
	ScriptContent  string            `json:"script_content"`
	ScriptName     string            `json:"script_name"`
	Args           []string          `json:"args,omitempty"`
	Env            map[string]string `json:"env,omitempty"`
	TimeoutSeconds int               `json:"timeout_seconds,omitempty"`
	WorkflowID     string            `json:"workflow_id,omitempty"`
}

// ExecuteResponse represents the result of script execution.
type ExecuteResponse struct {
	Stdout          string `json:"stdout"`
	Stderr          string `json:"stderr"`
	ExitCode        int    `json:"exit_code"`
	ExecutionTimeMs int64  `json:"execution_time_ms"`
}

func executeHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	noteRequest()

	var req ExecuteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid request: %v"}`, err), http.StatusBadRequest)
		return
	}

	if req.ScriptContent == "" || req.ScriptName == "" {
		http.Error(w, `{"error": "script_content and script_name are required"}`, http.StatusBadRequest)
		return
	}

	// Prevent path traversal — script_name must be a plain filename
	if filepath.Base(req.ScriptName) != req.ScriptName || strings.Contains(req.ScriptName, "..") {
		http.Error(w, `{"error": "script_name must be a simple filename without path separators"}`, http.StatusBadRequest)
		return
	}

	timeout := 30
	if req.TimeoutSeconds > 0 && req.TimeoutSeconds <= 300 {
		timeout = req.TimeoutSeconds
	}

	// Resolve the workspace.
	// - WorkflowID set → /workspace/wf-<id>/ (persistent across calls, no cleanup here).
	// - empty          → fresh tempdir, removed after the call (legacy stateless path).
	workspace, cleanupWorkspace, err := resolveWorkspace(req.WorkflowID)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusBadRequest)
		return
	}
	if cleanupWorkspace != nil {
		defer cleanupWorkspace()
	}

	// Build the command to run.
	// "cmd.sh" is the bash-tool shortcut: run the content directly via `sh -c`,
	// no script file written, no extension-based interpreter pick. SafeCommand
	// is intentionally NOT used here — its argument sanitiser rejects shell
	// metacharacters, which is exactly what `sh -c <content>` must accept.
	// Isolation is provided by the sandbox itself (pod / container boundary),
	// not by argv-level filtering.
	var cmd *exec.Cmd
	if req.ScriptName == "cmd.sh" {
		cmd = exec.Command("sh", "-c", req.ScriptContent) // nosemgrep: go.lang.security.audit.dangerous-exec-command.dangerous-exec-command // lgtm[go/command-injection]
	} else {
		// Determine interpreter from file extension
		ext := filepath.Ext(req.ScriptName)
		var interpreter string
		switch ext {
		case ".py":
			interpreter = "python3"
		case ".js":
			interpreter = "node"
		case ".sh":
			interpreter = "sh"
		default:
			http.Error(w, fmt.Sprintf(`{"error": "unsupported script type: %s"}`, ext), http.StatusBadRequest)
			return
		}

		// Write script to workspace — use cleaned filename to prevent path traversal
		cleanName := filepath.Base(req.ScriptName)
		scriptPath := filepath.Join(workspace, cleanName)
		if err := os.WriteFile(scriptPath, []byte(req.ScriptContent), 0500); err != nil {
			http.Error(w, fmt.Sprintf(`{"error": "failed to write script: %v"}`, err), http.StatusInternalServerError)
			return
		}

		cmdArgs := append([]string{scriptPath}, req.Args...)
		cmd, err = SafeCommand(interpreter, cmdArgs...)
		if err != nil {
			http.Error(w, fmt.Sprintf(`{"error": "invalid command: %v"}`, err), http.StatusBadRequest)
			return
		}
	}
	cmd.Dir = workspace

	// Build environment
	env := os.Environ()
	for k, v := range req.Env {
		if isValidEnvVarName(k) {
			env = append(env, fmt.Sprintf("%s=%s", k, v))
		}
	}
	cmd.Env = env

	// Capture output
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	start := time.Now()

	// Run with timeout
	if err := cmd.Start(); err != nil {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ExecuteResponse{
			Stderr:          fmt.Sprintf("failed to start: %v", err),
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
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ExecuteResponse{
			Stdout:          stdout.String(),
			Stderr:          stderr.String(),
			ExitCode:        exitCode,
			ExecutionTimeMs: elapsed,
		})

	case <-time.After(time.Duration(timeout) * time.Second):
		cmd.Process.Kill()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ExecuteResponse{
			Stderr:          "execution timed out",
			ExitCode:        137,
			ExecutionTimeMs: time.Since(start).Milliseconds(),
		})
	}

	logger.Info("Script executed",
		"script", req.ScriptName,
		"exit_code", stdout.Len(),
		"elapsed_ms", time.Since(start).Milliseconds(),
	)
}

// workspaceCleanupHandler removes /workspace/wf-<id>/ for a finished workflow.
// Called by mcp-manager (in dev mode where there is no pod to delete) when
// the workflow finalizer fires. In K8s production this endpoint is unused —
// the warm pool deletes the entire pod, taking the emptyDir with it.
func workspaceCleanupHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		WorkflowID string `json:"workflow_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid request: %v"}`, err), http.StatusBadRequest)
		return
	}
	if err := ValidateWorkflowID(req.WorkflowID); err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusBadRequest)
		return
	}
	dir := filepath.Join(workspaceRoot, "wf-"+req.WorkflowID)
	if err := ValidateFilePath(workspaceRoot, dir); err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "%s"}`, err.Error()), http.StatusBadRequest)
		return
	}
	if err := os.RemoveAll(dir); err != nil {
		logger.Error("workspace cleanup failed", "workflow_id", req.WorkflowID, "error", err)
		http.Error(w, fmt.Sprintf(`{"error": "cleanup failed: %v"}`, err), http.StatusInternalServerError)
		return
	}
	logger.Info("workspace cleaned up", "workflow_id", req.WorkflowID)
	w.WriteHeader(http.StatusNoContent)
}

// noteRequest records the time of the latest request for the idle watchdog.
func noteRequest() {
	lastRequestMu.Lock()
	lastRequest = time.Now()
	lastRequestMu.Unlock()
}

// startIdleWatchdog launches a goroutine that exits the process when no
// /execute or /activate request has arrived for IDLE_TIMEOUT_SECONDS. This
// is the backstop layer of the cleanup model: primary cleanup is an
// explicit DELETE from mcp-manager when the workflow finalizer fires; this
// watchdog only matters when that DELETE never arrives (worker crash,
// network partition, finalizer bug). Disabled when IDLE_TIMEOUT_SECONDS=0
// or unset.
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
			lastRequestMu.Unlock()
			if idle >= timeout {
				logger.Info("idle timeout reached, exiting", "idle_seconds", int(idle.Seconds()))
				os.Exit(0)
			}
		}
	}()
}

// resolveWorkspace returns the working directory for an /execute call.
// When workflowID is set the directory is /workspace/wf-<id>/ and persists
// across calls in that workflow — cleanup happens at pod tear-down. When
// workflowID is empty the directory is a fresh tempdir and the returned
// cleanup function removes it after the call (legacy stateless path).
func resolveWorkspace(workflowID string) (string, func(), error) {
	if workflowID == "" {
		dir, err := os.MkdirTemp("", "sandbox-*")
		if err != nil {
			return "", nil, fmt.Errorf("failed to create workspace: %w", err)
		}
		return dir, func() { _ = os.RemoveAll(dir) }, nil
	}

	if err := ValidateWorkflowID(workflowID); err != nil {
		return "", nil, err
	}

	dir := filepath.Join(workspaceRoot, "wf-"+workflowID)
	if err := ValidateFilePath(workspaceRoot, dir); err != nil {
		return "", nil, err
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", nil, fmt.Errorf("failed to create workflow workspace: %w", err)
	}
	return dir, nil, nil
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
