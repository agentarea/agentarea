package backends

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/container"
	"github.com/agentarea/mcp-manager/internal/models"
)

// DockerBackend implements the Backend interface using the existing container.Manager (Podman)
type DockerBackend struct {
	manager *container.Manager
	config  *config.Config
	logger  *slog.Logger
}

// NewDockerBackend creates a new Docker/Podman backend
func NewDockerBackend(cfg *config.Config, logger *slog.Logger) *DockerBackend {
	manager := container.NewManager(cfg, logger)

	return &DockerBackend{
		manager: manager,
		config:  cfg,
		logger:  logger,
	}
}

// GetManager returns the underlying container manager for backward compatibility
func (d *DockerBackend) GetManager() *container.Manager {
	return d.manager
}

// Initialize initializes the Docker backend
func (d *DockerBackend) Initialize(ctx context.Context) error {
	d.logger.Info("Initializing Docker backend")
	return d.manager.Initialize(ctx)
}

// CreateInstance creates a new MCP server instance using the existing container manager
func (d *DockerBackend) CreateInstance(ctx context.Context, spec *InstanceSpec) (*InstanceResult, error) {
	d.logger.Info("Creating instance with Docker backend",
		slog.String("name", spec.Name),
		slog.String("image", spec.Image))

	// Convert InstanceSpec to models.CreateContainerRequest
	req := d.specToCreateRequest(spec)

	// Use existing manager to create container
	container, err := d.manager.CreateContainer(ctx, req)
	if err != nil {
		d.logger.Error("Failed to create container via manager",
			slog.String("name", spec.Name),
			slog.String("error", err.Error()))
		return nil, fmt.Errorf("failed to create container: %w", err)
	}

	// Convert to InstanceResult
	result := &InstanceResult{
		ID:        container.ID,
		Name:      container.ServiceName,
		URL:       container.URL,
		Status:    string(container.Status),
		CreatedAt: container.CreatedAt,
	}

	d.logger.Info("Successfully created instance",
		slog.String("id", result.ID),
		slog.String("name", result.Name),
		slog.String("url", result.URL))

	return result, nil
}

// DeleteInstance removes an MCP server instance
func (d *DockerBackend) DeleteInstance(ctx context.Context, instanceID string) error {
	d.logger.Info("Deleting instance with Docker backend",
		slog.String("instance_id", instanceID))

	// Find container by ID or service name
	serviceName := d.findServiceNameByID(instanceID)
	if serviceName == "" {
		return fmt.Errorf("instance not found: %s", instanceID)
	}

	err := d.manager.DeleteContainer(ctx, serviceName)
	if err != nil {
		d.logger.Error("Failed to delete container",
			slog.String("instance_id", instanceID),
			slog.String("service_name", serviceName),
			slog.String("error", err.Error()))
		return fmt.Errorf("failed to delete container: %w", err)
	}

	d.logger.Info("Successfully deleted instance",
		slog.String("instance_id", instanceID),
		slog.String("service_name", serviceName))

	return nil
}

// GetInstanceStatus retrieves the current status of an instance
func (d *DockerBackend) GetInstanceStatus(ctx context.Context, instanceID string) (*InstanceStatus, error) {
	serviceName := d.findServiceNameByID(instanceID)
	if serviceName == "" {
		return nil, fmt.Errorf("instance not found: %s", instanceID)
	}

	container, err := d.manager.GetContainer(serviceName)
	if err != nil {
		return nil, fmt.Errorf("failed to get container: %w", err)
	}

	// Get real-time status
	status, err := d.manager.GetContainerStatus(ctx, serviceName)
	if err != nil {
		d.logger.Warn("Failed to get real-time status, using cached",
			slog.String("service_name", serviceName),
			slog.String("error", err.Error()))
		status = container.Status
	}

	// Get health check result
	var healthStatus *HealthCheckResult
	if healthResult, exists := d.manager.GetContainerHealthStatus(serviceName); exists {
		healthStatus = &HealthCheckResult{
			Healthy:       healthResult.Healthy,
			Status:        string(healthResult.Status),
			HTTPReachable: healthResult.HTTPReachable,
			ResponseTime:  healthResult.ResponseTime,
			ContainerID:   healthResult.ContainerID,
			ServiceName:   healthResult.ServiceName,
			Error:         healthResult.Error,
			Details:       healthResult.Details,
			Timestamp:     healthResult.Timestamp,
		}
	}

	instanceStatus := &InstanceStatus{
		ID:           container.ID,
		Name:         container.ServiceName,
		ServiceName:  container.ServiceName,
		Status:       string(status),
		URL:          container.URL,
		Image:        container.Image,
		Port:         container.Port,
		Environment:  container.Environment,
		Labels:       container.Labels,
		CreatedAt:    container.CreatedAt,
		UpdatedAt:    container.UpdatedAt,
		HealthStatus: healthStatus,
	}

	return instanceStatus, nil
}

// ListInstances returns all managed instances
func (d *DockerBackend) ListInstances(ctx context.Context) ([]*InstanceStatus, error) {
	containers := d.manager.ListContainers()
	instances := make([]*InstanceStatus, 0, len(containers))

	for _, container := range containers {
		// Get health status if available
		var healthStatus *HealthCheckResult
		if healthResult, exists := d.manager.GetContainerHealthStatus(container.ServiceName); exists {
			healthStatus = &HealthCheckResult{
				Healthy:       healthResult.Healthy,
				Status:        string(healthResult.Status),
				HTTPReachable: healthResult.HTTPReachable,
				ResponseTime:  healthResult.ResponseTime,
				ContainerID:   healthResult.ContainerID,
				ServiceName:   healthResult.ServiceName,
				Error:         healthResult.Error,
				Details:       healthResult.Details,
				Timestamp:     healthResult.Timestamp,
			}
		}

		instance := &InstanceStatus{
			ID:           container.ID,
			Name:         container.ServiceName,
			ServiceName:  container.ServiceName,
			Status:       string(container.Status),
			URL:          container.URL,
			Image:        container.Image,
			Port:         container.Port,
			Environment:  container.Environment,
			Labels:       container.Labels,
			CreatedAt:    container.CreatedAt,
			UpdatedAt:    container.UpdatedAt,
			HealthStatus: healthStatus,
		}

		instances = append(instances, instance)
	}

	return instances, nil
}

// UpdateInstance updates an existing instance configuration
func (d *DockerBackend) UpdateInstance(ctx context.Context, instanceID string, spec *InstanceSpec) error {
	d.logger.Info("Updating instance with Docker backend",
		slog.String("instance_id", instanceID))

	// For Docker backend, we need to recreate the container
	// First delete the existing instance
	if err := d.DeleteInstance(ctx, instanceID); err != nil {
		return fmt.Errorf("failed to delete existing instance: %w", err)
	}

	// Then create a new one with updated spec
	_, err := d.CreateInstance(ctx, spec)
	if err != nil {
		return fmt.Errorf("failed to recreate instance: %w", err)
	}

	return nil
}

// PerformHealthCheck performs health check on an instance
func (d *DockerBackend) PerformHealthCheck(ctx context.Context, instanceID string) (*HealthCheckResult, error) {
	serviceName := d.findServiceNameByID(instanceID)
	if serviceName == "" {
		return nil, fmt.Errorf("instance not found: %s", instanceID)
	}

	healthData, err := d.manager.PerformHealthCheck(ctx, serviceName)
	if err != nil {
		return nil, fmt.Errorf("health check failed: %w", err)
	}

	// Convert map to HealthCheckResult
	result := &HealthCheckResult{
		ServiceName: serviceName,
		Timestamp:   time.Now(),
	}

	if healthy, ok := healthData["healthy"].(bool); ok {
		result.Healthy = healthy
	}

	if status, ok := healthData["container_status"].(string); ok {
		result.Status = status
	}

	if reachable, ok := healthData["http_reachable"].(bool); ok {
		result.HTTPReachable = reachable
	}

	if responseTime, ok := healthData["response_time_ms"].(int64); ok {
		result.ResponseTime = time.Duration(responseTime) * time.Millisecond
	}

	if containerID, ok := healthData["container_id"].(string); ok {
		result.ContainerID = containerID
	}

	if errorMsg, ok := healthData["error"].(string); ok {
		result.Error = errorMsg
	}

	if details, ok := healthData["details"]; ok {
		result.Details = details
	}

	return result, nil
}

// Shutdown gracefully shuts down the Docker backend
func (d *DockerBackend) Shutdown(ctx context.Context) error {
	d.logger.Info("Shutting down Docker backend")
	return d.manager.Shutdown(ctx)
}

// Helper methods

// specToCreateRequest converts InstanceSpec to models.CreateContainerRequest
func (d *DockerBackend) specToCreateRequest(spec *InstanceSpec) models.CreateContainerRequest {
	req := models.CreateContainerRequest{
		ServiceName: spec.ServiceName,
		Image:       spec.Image,
		Port:        spec.Port,
		Environment: spec.Environment,
		Labels:      spec.Labels,
		Command:     spec.Command,
	}

	// Add resource limits if specified
	if spec.Resources.Limits.Memory != "" {
		req.MemoryLimit = spec.Resources.Limits.Memory
	}
	if spec.Resources.Limits.CPU != "" {
		req.CPULimit = spec.Resources.Limits.CPU
	}

	// Add MCP-specific environment variables
	if req.Environment == nil {
		req.Environment = make(map[string]string)
	}
	req.Environment["MCP_INSTANCE_ID"] = spec.InstanceID
	req.Environment["MCP_SERVICE_NAME"] = spec.ServiceName
	req.Environment["MCP_CONTAINER_PORT"] = fmt.Sprintf("%d", spec.Port)

	return req
}

// findServiceNameByID finds the service name by container ID or instance ID
func (d *DockerBackend) findServiceNameByID(instanceID string) string {
	containers := d.manager.ListContainers()

	for _, container := range containers {
		// Check if ID matches
		if container.ID == instanceID {
			return container.ServiceName
		}

		// Check if instance ID matches from environment
		if mcpInstanceID, exists := container.Environment["MCP_INSTANCE_ID"]; exists {
			if mcpInstanceID == instanceID {
				return container.ServiceName
			}
		}

		// Check if service name matches directly
		if container.ServiceName == instanceID {
			return container.ServiceName
		}
	}

	return ""
}
