// Activation service runs inside warm pods
// Handles on-demand MCP activation via HTTP API

package main

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
)

var (
	status     = "waiting"
	mcpProcess *os.Process
	logger     *slog.Logger
)

type ActivateRequest struct {
	MCPImage     string            `json:"mcp_image"`
	MCPImageHash string            `json:"mcp_image_hash"`
	Env          map[string]string `json:"env"`
	Config       json.RawMessage   `json:"config,omitempty"`
}

type ActivateResponse struct {
	Status           string `json:"status"`
	MCPPort          int    `json:"mcp_port"`
	ActivationTimeMs int    `json:"activation_time_ms"`
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

	logger.Info("Listening", "port", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		logger.Error("Server failed", "error", err)
		os.Exit(1)
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	response := map[string]string{
		"status": status,
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func activateHandler(w http.ResponseWriter, r *http.Request) {
	start := time.Now()

	if status != "waiting" {
		http.Error(w, `{"error": "pod already assigned"}`, http.StatusConflict)
		return
	}

	var req ActivateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "invalid request: %v"}`, err), http.StatusBadRequest)
		return
	}

	logger.Info("Activation requested",
		"image", req.MCPImage,
		"hash", req.MCPImageHash,
	)

	status = "activating"

	if err := activate(req); err != nil {
		status = "waiting"
		logger.Error("Activation failed", "error", err)
		http.Error(w, fmt.Sprintf(`{"error": "%v"}`, err), http.StatusInternalServerError)
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
		MCPPort:          3000,
		ActivationTimeMs: int(elapsed),
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func activate(req ActivateRequest) error {
	// Step 1: Download/extract MCP image
	if err := prepareMCP(req.MCPImage, req.MCPImageHash); err != nil {
		return fmt.Errorf("failed to prepare MCP: %w", err)
	}

	// Step 2: Set environment
	for k, v := range req.Env {
		os.Setenv(k, v)
	}

	// Step 3: Start MCP process
	if err := startMCP(); err != nil {
		return fmt.Errorf("failed to start MCP: %w", err)
	}

	// Step 4: Wait for ready
	if err := waitForReady(30 * time.Second); err != nil {
		if mcpProcess != nil {
			mcpProcess.Kill()
		}
		return fmt.Errorf("MCP failed to become ready: %w", err)
	}

	return nil
}

func prepareMCP(image, hash string) error {
	cacheDir := "/var/cache/mcp-images"
	extractDir := "/app/mcp-overlay"

	// Ensure directories exist
	if err := os.MkdirAll(cacheDir, 0755); err != nil {
		return err
	}
	if err := os.MkdirAll(extractDir, 0755); err != nil {
		return err
	}

	imagePath := filepath.Join(cacheDir, hash+".tar")

	// Check if already cached
	if _, err := os.Stat(imagePath); os.IsNotExist(err) {
		logger.Info("Downloading MCP image", "image", image)

		// Pull image using skopeo or similar
		// For now, use a simple download command
		cmd := exec.Command("skopeo", "copy", "docker://"+image, "docker-archive:"+imagePath)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr

		if err := cmd.Run(); err != nil {
			// Fallback: try wget for tar.gz URLs
			logger.Warn("Skopeo failed, trying direct download", "error", err)
			// In real implementation, handle different image formats
		}
	} else {
		logger.Info("Using cached MCP image", "path", imagePath)
	}

	// Extract image
	logger.Info("Extracting MCP image")
	if err := extractImage(imagePath, extractDir); err != nil {
		return fmt.Errorf("failed to extract: %w", err)
	}

	// Perform overlay mount
	logger.Info("Mounting overlay")
	if err := mountOverlay(); err != nil {
		return fmt.Errorf("failed to mount overlay: %w", err)
	}

	return nil
}

func extractImage(imagePath, extractDir string) error {
	// Clean extract directory
	if err := os.RemoveAll(extractDir); err != nil {
		return err
	}
	if err := os.MkdirAll(extractDir, 0755); err != nil {
		return err
	}

	// Extract tar
	cmd := exec.Command("tar", "-xf", imagePath, "-C", extractDir)
	return cmd.Run()
}

func mountOverlay() error {
	lowerDir := "/app/base"       // Base runner files
	upperDir := "/app/mcp-overlay" // MCP-specific files
	workDir := "/tmp/overlay-work"
	mergeDir := "/app/mcp"

	// Ensure directories exist
	for _, dir := range []string{lowerDir, workDir, mergeDir} {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return err
		}
	}

	// Unmount if already mounted (cleanup from previous activation)
	exec.Command("umount", mergeDir).Run()

	// Mount overlay
	options := fmt.Sprintf("lowerdir=%s,upperdir=%s,workdir=%s", lowerDir, upperDir, workDir)
	cmd := exec.Command("mount", "-t", "overlay", "overlay", "-o", options, mergeDir)
	return cmd.Run()
}

func startMCP() error {
	startScript := "/app/mcp/start.sh"

	// Check if start script exists
	if _, err := os.Stat(startScript); os.IsNotExist(err) {
		// Try alternative entry points
		startScript = "/app/mcp/entrypoint.sh"
		if _, err := os.Stat(startScript); os.IsNotExist(err) {
			startScript = "/app/mcp/run"
		}
	}

	logger.Info("Starting MCP", "script", startScript)

	cmd := exec.Command(startScript)
	cmd.Dir = "/app/mcp"
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Setpgid: true,
	}
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return err
	}

	mcpProcess = cmd.Process
	logger.Info("MCP process started", "pid", mcpProcess.Pid)

	return nil
}

func waitForReady(timeout time.Duration) error {
	start := time.Now()
	mcpPort := os.Getenv("MCP_PORT")
	if mcpPort == "" {
		mcpPort = "3000"
	}

	for time.Since(start) < timeout {
		// Try to connect to MCP health endpoint
		resp, err := http.Get("http://localhost:" + mcpPort + "/health")
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				return nil
			}
		}
		time.Sleep(100 * time.Millisecond)
	}

	return fmt.Errorf("timeout waiting for MCP ready")
}
