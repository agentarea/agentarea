// Activation service runs inside warm pods
// Handles on-demand MCP activation via HTTP API
package main

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

var (
	status     = "waiting"
	mcpProcess *os.Process
	logger     *slog.Logger
)

// ActivateRequest represents the activation request
type ActivateRequest struct {
	MCPImage     string            `json:"mcp_image"`
	MCPImageHash string            `json:"mcp_image_hash"`
	Port         int               `json:"port"`
	Entrypoint   []string          `json:"entrypoint"`
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

	port := os.Getenv("ACTIVATION_PORT")
	if port == "" {
		port = "8080"
	}

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
	logger.Info("Request decoded", "image", req.MCPImage, "port", req.Port, "entrypoint", req.Entrypoint, "command", req.Command)

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

	// Security: Validate entrypoint and command arguments
	if len(req.Entrypoint) > 0 {
		if err := ValidateCommandArgs(req.Entrypoint); err != nil {
			logger.Error("Entrypoint validation failed", "error", err)
			http.Error(w, fmt.Sprintf(`{"error": "invalid entrypoint: %s"}`, err.Error()), http.StatusBadRequest)
			return
		}
	}
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

	// Step 2: Parse image config and resolve entrypoint/command
	imageConfig, err := ParseImageConfig(extractDir)
	if err != nil {
		logger.Warn("Failed to parse image config, will rely on user-provided values", "error", err)
		imageConfig = nil
	}

	entrypoint, command := GetEffectiveCommand(imageConfig, req.Entrypoint, req.Command)

	if err := ValidateCommand(entrypoint, command); err != nil {
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

	// Try chroot first (requires privileged mode)
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
		logger.Warn("Chroot failed, falling back to direct execution", "error", err)

		// Fallback: direct execution with modified environment
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
	// Prepend container paths to PATH for fallback execution
	paths := []string{
		filepath.Join(rootDir, "usr/local/sbin"),
		filepath.Join(rootDir, "usr/local/bin"),
		filepath.Join(rootDir, "usr/sbin"),
		filepath.Join(rootDir, "usr/bin"),
		filepath.Join(rootDir, "sbin"),
		filepath.Join(rootDir, "bin"),
	}

	// Get existing PATH
	existingPath := os.Getenv("PATH")
	if existingPath != "" {
		paths = append(paths, existingPath)
	}

	return []string{"PATH=" + strings.Join(paths, ":")}
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
