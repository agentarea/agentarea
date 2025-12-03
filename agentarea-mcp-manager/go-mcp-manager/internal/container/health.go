package container

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

// HealthChecker handles health checks for MCP containers
type HealthChecker struct {
	logger     *slog.Logger
	config     *config.Config
	httpClient *http.Client
}

// NewHealthChecker creates a new health checker
func NewHealthChecker(cfg *config.Config, logger *slog.Logger) *HealthChecker {
	return &HealthChecker{
		logger: logger,
		config: cfg,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// HealthCheckResult represents the result of a health check
type HealthCheckResult struct {
	ContainerID   string                 `json:"container_id"`
	ServiceName   string                 `json:"service_name"`
	Healthy       bool                   `json:"healthy"`
	Status        models.ContainerStatus `json:"status"`
	HTTPReachable bool                   `json:"http_reachable"`
	ResponseTime  time.Duration          `json:"response_time"`
	Error         string                 `json:"error,omitempty"`
	Timestamp     time.Time              `json:"timestamp"`
	Details       map[string]interface{} `json:"details,omitempty"`
}

// PerformHealthCheck performs a comprehensive health check on a container
func (h *HealthChecker) PerformHealthCheck(ctx context.Context, container *models.Container) (*HealthCheckResult, error) {
	h.logger.Info("Performing health check",
		slog.String("container", container.Name),
		slog.String("service", container.ServiceName))

	result := &HealthCheckResult{
		ContainerID: container.ID,
		ServiceName: container.ServiceName,
		Timestamp:   time.Now(),
		Details:     make(map[string]interface{}),
	}

	// Check real-time container status from Podman
	realTimeStatus := h.getRealTimeContainerStatus(ctx, container)
	result.Status = realTimeStatus

	// Check container health based on real-time status
	containerHealthy := h.checkContainerStatusRealTime(realTimeStatus)
	result.Healthy = containerHealthy

	if !containerHealthy {
		result.Error = "Container is not running"
		return result, nil
	}

	// Perform HTTP health check if container is running
	if realTimeStatus == models.StatusRunning {
		// Get container IP for direct access instead of using proxy URL
		containerIP, err := h.getContainerIP(ctx, container.ID)
		if err != nil {
			h.logger.Warn("Failed to get container IP for health check",
				slog.String("container", container.Name),
				slog.String("error", err.Error()))
			// If we can't get IP, skip HTTP health check but consider container healthy since it's running
			result.Healthy = true
			result.HTTPReachable = false
			result.Error = "Could not determine container IP for health check"
		} else {
			// Get the container's internal exposed port
			internalPort, err := h.getContainerExposedPort(ctx, container.ID)
			if err != nil {
				h.logger.Warn("Failed to get container exposed port for health check",
					slog.String("container", container.Name),
					slog.String("error", err.Error()))
				// Skip HTTP health check but consider container healthy since it's running
				result.Healthy = true
				result.HTTPReachable = false
				result.Error = "Could not determine container exposed port for health check"
			} else {
				// Construct direct URL to container using internal port
				directURL := fmt.Sprintf("http://%s:%d", containerIP, internalPort)

				httpHealthy, responseTime, err := h.checkHTTPEndpoint(ctx, directURL)
				result.HTTPReachable = httpHealthy
				result.ResponseTime = responseTime

				if err != nil {
					result.Error = err.Error()
					result.Healthy = false
				} else if !httpHealthy {
					result.Error = "HTTP endpoint not reachable"
					result.Healthy = false
				}

				result.Details["direct_http_endpoint"] = directURL
				result.Details["internal_port"] = internalPort
				result.Details["response_time_ms"] = responseTime.Milliseconds()
			}
		}

		// Always include the proxy URL for reference
		result.Details["proxy_url"] = container.URL
	}

	// Add additional container details
	result.Details["container_port"] = container.Port
	result.Details["container_image"] = container.Image
	result.Details["created_at"] = container.CreatedAt
	result.Details["updated_at"] = container.UpdatedAt

	h.logger.Info("Health check completed",
		slog.String("container", container.Name),
		slog.Bool("healthy", result.Healthy),
		slog.Bool("http_reachable", result.HTTPReachable),
		slog.Duration("response_time", result.ResponseTime))

	return result, nil
}

// getRealTimeContainerStatus gets the real-time status from Runtime
func (h *HealthChecker) getRealTimeContainerStatus(ctx context.Context, container *models.Container) models.ContainerStatus {
	if container.ID == "" {
		return models.StatusError
	}

	cmd := exec.CommandContext(ctx, h.config.Container.Runtime, "inspect", container.ID, "--format", "{{.State.Status}}")
	output, err := cmd.CombinedOutput()
	if err != nil {
		h.logger.Error("Failed to get real-time container status",
			slog.String("container", container.Name),
			slog.String("error", err.Error()))
		return models.StatusError
	}

	podmanStatus := strings.TrimSpace(string(output))
	return h.mapPodmanStatus(podmanStatus)
}

// mapPodmanStatus maps Podman status to our container status
func (h *HealthChecker) mapPodmanStatus(podmanStatus string) models.ContainerStatus {
	switch strings.ToLower(podmanStatus) {
	case "running":
		return models.StatusRunning
	case "exited", "stopped":
		return models.StatusStopped
	case "created", "configured":
		return models.StatusStarting
	case "stopping":
		return models.StatusStopping
	default:
		return models.StatusError
	}
}

// checkContainerStatusRealTime checks if the container is in a healthy state based on real-time status
func (h *HealthChecker) checkContainerStatusRealTime(status models.ContainerStatus) bool {
	switch status {
	case models.StatusRunning, models.StatusHealthy:
		return true
	case models.StatusStarting:
		// Starting containers might become healthy soon
		return false
	default:
		return false
	}
}

// checkHTTPEndpoint checks if the HTTP endpoint is reachable
func (h *HealthChecker) checkHTTPEndpoint(ctx context.Context, url string) (bool, time.Duration, error) {
	start := time.Now()

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return false, 0, fmt.Errorf("failed to create HTTP request: %w", err)
	}

	resp, err := h.httpClient.Do(req)
	responseTime := time.Since(start)

	if err != nil {
		return false, responseTime, fmt.Errorf("HTTP request failed: %w", err)
	}
	defer resp.Body.Close()

	// Consider 2xx and 3xx status codes as healthy
	healthy := resp.StatusCode >= 200 && resp.StatusCode < 400

	return healthy, responseTime, nil
}

// PerformBulkHealthCheck performs health checks on multiple containers
func (h *HealthChecker) PerformBulkHealthCheck(ctx context.Context, containers []*models.Container) ([]*HealthCheckResult, error) {
	results := make([]*HealthCheckResult, 0, len(containers))

	for _, container := range containers {
		result, err := h.PerformHealthCheck(ctx, container)
		if err != nil {
			h.logger.Error("Health check failed for container",
				slog.String("container", container.Name),
				slog.String("error", err.Error()))

			// Create error result
			result = &HealthCheckResult{
				ContainerID: container.ID,
				ServiceName: container.ServiceName,
				Healthy:     false,
				Status:      container.Status,
				Error:       err.Error(),
				Timestamp:   time.Now(),
			}
		}
		results = append(results, result)
	}

	return results, nil
}

// MonitorContainerHealth starts monitoring container health continuously
func (h *HealthChecker) MonitorContainerHealth(ctx context.Context, container *models.Container, interval time.Duration, callback func(*HealthCheckResult)) {
	h.logger.Info("Starting health monitoring",
		slog.String("container", container.Name),
		slog.Duration("interval", interval))

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			h.logger.Info("Health monitoring stopped",
				slog.String("container", container.Name))
			return
		case <-ticker.C:
			result, err := h.PerformHealthCheck(ctx, container)
			if err != nil {
				h.logger.Error("Health monitoring check failed",
					slog.String("container", container.Name),
					slog.String("error", err.Error()))
				continue
			}

			if callback != nil {
				callback(result)
			}

			// Log health status changes
			if !result.Healthy {
				h.logger.Warn("Container health check failed",
					slog.String("container", container.Name),
					slog.String("error", result.Error))
			}
		}
	}
}

// GetHealthSummary returns a summary of health for all provided containers
func (h *HealthChecker) GetHealthSummary(ctx context.Context, containers []*models.Container) (map[string]interface{}, error) {
	results, err := h.PerformBulkHealthCheck(ctx, containers)
	if err != nil {
		return nil, err
	}

	summary := map[string]interface{}{
		"total_containers":     len(results),
		"healthy_containers":   0,
		"unhealthy_containers": 0,
		"running_containers":   0,
		"stopped_containers":   0,
		"error_containers":     0,
		"timestamp":            time.Now(),
	}

	healthyCount := 0
	runningCount := 0
	stoppedCount := 0
	errorCount := 0

	for _, result := range results {
		if result.Healthy {
			healthyCount++
		}

		switch result.Status {
		case models.StatusRunning:
			runningCount++
		case models.StatusStopped:
			stoppedCount++
		case models.StatusError:
			errorCount++
		}
	}

	summary["healthy_containers"] = healthyCount
	summary["unhealthy_containers"] = len(results) - healthyCount
	summary["running_containers"] = runningCount
	summary["stopped_containers"] = stoppedCount
	summary["error_containers"] = errorCount

	return summary, nil
}

// getContainerIP retrieves the IP address of a container
func (h *HealthChecker) getContainerIP(ctx context.Context, containerID string) (string, error) {
	cmd := exec.CommandContext(ctx, h.config.Container.Runtime, "inspect", containerID, "--format", "{{.NetworkSettings.IPAddress}}")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("failed to get container IP: %w", err)
	}

	ip := strings.TrimSpace(string(output))
	if ip == "" {
		// Try alternative format for newer podman versions
		cmd = exec.CommandContext(ctx, h.config.Container.Runtime, "inspect", containerID, "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}")
		output, err = cmd.CombinedOutput()
		if err != nil {
			return "", fmt.Errorf("failed to get container IP (alternative): %w", err)
		}
		ip = strings.TrimSpace(string(output))
	}

	if ip == "" {
		return "", fmt.Errorf("container IP address is empty")
	}

	return ip, nil
}

// getContainerExposedPort retrieves the first exposed HTTP port from a container
func (h *HealthChecker) getContainerExposedPort(ctx context.Context, containerID string) (int, error) {
	cmd := exec.CommandContext(ctx, h.config.Container.Runtime, "inspect", containerID, "--format", "{{range $port, $config := .Config.ExposedPorts}}{{$port}} {{end}}")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return 0, fmt.Errorf("failed to get container exposed ports: %w", err)
	}

	portsStr := strings.TrimSpace(string(output))
	if portsStr == "" {
		// No exposed ports found, try common HTTP ports
		return h.guessHTTPPort(ctx, containerID)
	}

	// Parse exposed ports (format: "80/tcp 443/tcp")
	ports := strings.Fields(portsStr)
	for _, port := range ports {
		if strings.HasSuffix(port, "/tcp") {
			portNumStr := strings.TrimSuffix(port, "/tcp")
			if portNum, err := strconv.Atoi(portNumStr); err == nil {
				// Return the first TCP port (likely HTTP)
				return portNum, nil
			}
		}
	}

	// If no TCP ports found, try to guess
	return h.guessHTTPPort(ctx, containerID)
}

// guessHTTPPort tries to guess the HTTP port based on common patterns
func (h *HealthChecker) guessHTTPPort(ctx context.Context, containerID string) (int, error) {
	// Get container image to make educated guesses
	cmd := exec.CommandContext(ctx, h.config.Container.Runtime, "inspect", containerID, "--format", "{{.Config.Image}}")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return 80, nil // Default to port 80
	}

	image := strings.TrimSpace(string(output))
	imageLower := strings.ToLower(image)

	// Common HTTP port mappings
	if strings.Contains(imageLower, "nginx") {
		return 80, nil
	} else if strings.Contains(imageLower, "apache") || strings.Contains(imageLower, "httpd") {
		return 80, nil
	} else if strings.Contains(imageLower, "node") {
		return 3000, nil
	} else if strings.Contains(imageLower, "flask") || strings.Contains(imageLower, "python") {
		return 5000, nil
	} else if strings.Contains(imageLower, "rails") || strings.Contains(imageLower, "ruby") {
		return 3000, nil
	}

	// Default to port 80 for HTTP services
	return 80, nil
}
