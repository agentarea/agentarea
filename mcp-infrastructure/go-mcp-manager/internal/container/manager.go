package container

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/events"
	"github.com/agentarea/mcp-manager/internal/models"
)

// Manager manages container lifecycle for MCP servers
type Manager struct {
	config          *config.Config
	containers      map[string]*models.Container
	containerHealth map[string]*HealthCheckResult // Track health status
	mutex           sync.RWMutex
	logger          *slog.Logger
	traefikManager  *TraefikManager
	validator       *ContainerValidator
	healthChecker   *HealthChecker
	eventPublisher  *events.EventPublisher
	healthCtx       context.Context
	healthCancel    context.CancelFunc
}

// NewManager creates a new container manager with Traefik integration
func NewManager(cfg *config.Config, logger *slog.Logger) *Manager {
	traefikManager := NewTraefikManager(cfg, logger)
	healthChecker := NewHealthChecker(logger)
	eventPublisher := events.NewEventPublisher(cfg.Redis.URL, logger)

	// Create context for health monitoring
	healthCtx, healthCancel := context.WithCancel(context.Background())

	manager := &Manager{
		config:          cfg,
		containers:      make(map[string]*models.Container),
		containerHealth: make(map[string]*HealthCheckResult),
		logger:          logger,
		traefikManager:  traefikManager,
		healthChecker:   healthChecker,
		eventPublisher:  eventPublisher,
		healthCtx:       healthCtx,
		healthCancel:    healthCancel,
	}

	// Create validator with manager reference (after manager is created)
	manager.validator = NewContainerValidator(logger, manager)

	return manager
}

// Initialize initializes the container manager
func (m *Manager) Initialize(ctx context.Context) error {
	m.logger.Info("Initializing container manager")

	// Start health monitoring in background
	m.logger.Info("Starting health monitoring...")
	go m.startHealthMonitoring()
	m.logger.Info("Health monitoring started")

	// Discover existing containers
	m.logger.Info("Discovering existing containers...")
	if err := m.discoverContainers(ctx); err != nil {
		m.logger.Error("Failed to discover containers", slog.String("error", err.Error()))
		return err
	}
	m.logger.Info("Container discovery completed")

	// Synchronize with Core API to handle pending instances
	m.logger.Info("Starting Core API synchronization...")
	if err := m.syncWithCoreAPI(ctx); err != nil {
		m.logger.Error("Failed to sync with Core API", slog.String("error", err.Error()))
		// Don't fail initialization - log warning and continue
		m.logger.Warn("Continuing without full sync - some instances may need manual intervention")
	}
	m.logger.Info("Core API synchronization completed")

	// Auto-restart containers that should be running
	m.logger.Info("Starting auto-restart check...")
	if err := m.autoRestartContainers(ctx); err != nil {
		m.logger.Error("Failed to auto-restart containers", slog.String("error", err.Error()))
		// Don't fail initialization - this is not critical
	}
	m.logger.Info("Auto-restart check completed")

	m.logger.Info("Container manager initialized successfully")
	return nil
}

// CreateContainer creates a new container from a template
func (m *Manager) CreateContainer(ctx context.Context, req models.CreateContainerRequest) (*models.Container, error) {
	m.mutex.Lock()
	defer m.mutex.Unlock()

	// Check if container already exists
	if _, exists := m.containers[req.ServiceName]; exists {
		return nil, fmt.Errorf("container %s already exists", req.ServiceName)
	}

	// Generate container name using the sanitized service name
	containerName := m.config.GetContainerName(req.ServiceName)

	// Check container limit
	if len(m.containers) >= m.config.Container.MaxContainers {
		return nil, fmt.Errorf("maximum container limit reached (%d)", m.config.Container.MaxContainers)
	}

	// Generate slug for consistent URL routing
	slug := generateSlug(req.ServiceName)

	// Create container directly from request
	container := &models.Container{
		Name:        containerName,
		ServiceName: req.ServiceName,
		Slug:        slug,
		Image:       req.Image,
		Status:      models.StatusStarting,
		Port:        req.Port,
		URL:         fmt.Sprintf("%s/mcp/%s", m.config.Traefik.ProxyHost, slug),
		Host:        m.config.Traefik.ProxyHost,
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
		Labels:      req.Labels,
		Environment: req.Environment,
	}

	// Build podman run command
	args := m.buildPodmanRunArgs(container)

	// Execute podman run
	cmd := exec.CommandContext(ctx, "podman", args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		container.Status = models.StatusError
		m.logger.Error("Failed to create container",
			slog.String("container", containerName),
			slog.String("error", err.Error()),
			slog.String("output", string(output)))
		return nil, fmt.Errorf("failed to create container: %w", err)
	}

	// Get container ID from output
	container.ID = strings.TrimSpace(string(output))

	// Wait for container to be running
	if err := m.waitForContainer(ctx, container.ID); err != nil {
		container.Status = models.StatusError
		return nil, fmt.Errorf("container failed to start: %w", err)
	}

	// Get container IP for Traefik routing
	containerIP, err := m.getContainerIP(ctx, container.ID)
	if err != nil {
		m.logger.Error("Failed to get container IP",
			slog.String("container", containerName),
			slog.String("error", err.Error()))
		// Continue without IP - container is still created
		containerIP = "127.0.0.1" // fallback
	}

	// Add Traefik route for the container using the slug
	if err := m.traefikManager.AddMCPService(ctx, slug, containerIP, req.Port); err != nil {
		m.logger.Error("Failed to add Traefik route",
			slog.String("slug", slug),
			slog.String("service", req.ServiceName),
			slog.String("error", err.Error()))
		// Continue - container is created but routing may not work
	}

	container.Status = models.StatusRunning
	m.containers[req.ServiceName] = container

	m.logger.Info("Container created successfully with slug",
		slog.String("container", containerName),
		slog.String("id", container.ID),
		slog.String("service", req.ServiceName),
		slog.String("slug", slug),
		slog.String("url", container.URL),
		slog.String("container_ip", containerIP))

	return container, nil
}

// GetContainer gets a container by service name
func (m *Manager) GetContainer(serviceName string) (*models.Container, error) {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	container, exists := m.containers[serviceName]
	if !exists {
		return nil, fmt.Errorf("container %s not found", serviceName)
	}

	return container, nil
}

// ListContainers returns all managed containers
func (m *Manager) ListContainers() []models.Container {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	containers := make([]models.Container, 0, len(m.containers))
	for _, container := range m.containers {
		containers = append(containers, *container)
	}

	return containers
}

// GetContainerStatus gets the real-time status of a container
func (m *Manager) GetContainerStatus(ctx context.Context, serviceName string) (models.ContainerStatus, error) {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	container, exists := m.containers[serviceName]
	if !exists {
		return models.StatusError, fmt.Errorf("container %s not found", serviceName)
	}

	// Get real-time status from podman
	cmd := exec.CommandContext(ctx, "podman", "inspect", container.ID, "--format", "{{.State.Status}}")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return models.StatusError, fmt.Errorf("failed to get container status: %w", err)
	}

	podmanStatus := strings.TrimSpace(string(output))
	status := m.mapPodmanStatus(podmanStatus)

	// Update cached status
	m.mutex.RUnlock()
	m.mutex.Lock()
	container.Status = status
	m.mutex.Unlock()
	m.mutex.RLock()

	return status, nil
}

// PerformHealthCheck performs an HTTP health check on a container
func (m *Manager) PerformHealthCheck(ctx context.Context, serviceName string) (map[string]interface{}, error) {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	container, exists := m.containers[serviceName]
	if !exists {
		return nil, fmt.Errorf("container %s not found", serviceName)
	}

	// Use health checker to perform comprehensive health check
	healthResult, err := m.healthChecker.PerformHealthCheck(ctx, container)
	if err != nil {
		return nil, fmt.Errorf("health check failed: %w", err)
	}

	// Convert health result to map for JSON response
	result := map[string]interface{}{
		"service_name":     serviceName,
		"container_id":     healthResult.ContainerID,
		"container_status": string(healthResult.Status),
		"healthy":          healthResult.Healthy,
		"http_reachable":   healthResult.HTTPReachable,
		"response_time_ms": healthResult.ResponseTime.Milliseconds(),
		"timestamp":        healthResult.Timestamp,
		"url":              container.URL,
		"slug":             container.Slug,
	}

	if healthResult.Error != "" {
		result["error"] = healthResult.Error
	}

	if healthResult.Details != nil {
		result["details"] = healthResult.Details
	}

	return result, nil
}

// DeleteContainer stops and removes a container
func (m *Manager) DeleteContainer(ctx context.Context, serviceName string) error {
	m.mutex.Lock()
	defer m.mutex.Unlock()

	container, exists := m.containers[serviceName]
	if !exists {
		return fmt.Errorf("container %s not found", serviceName)
	}

	container.Status = models.StatusStopping

	// Stop container
	stopCmd := exec.CommandContext(ctx, "podman", "stop", container.ID)
	if output, err := stopCmd.CombinedOutput(); err != nil {
		m.logger.Error("Failed to stop container",
			slog.String("container", container.Name),
			slog.String("error", err.Error()),
			slog.String("output", string(output)))
	}

	// Remove container
	rmCmd := exec.CommandContext(ctx, "podman", "rm", container.ID)
	if output, err := rmCmd.CombinedOutput(); err != nil {
		m.logger.Error("Failed to remove container",
			slog.String("container", container.Name),
			slog.String("error", err.Error()),
			slog.String("output", string(output)))
		return fmt.Errorf("failed to remove container: %w", err)
	}

	// Remove Traefik route for the container using the slug
	if container.Slug != "" {
		if err := m.traefikManager.RemoveMCPService(ctx, container.Slug); err != nil {
			m.logger.Error("Failed to remove Traefik route",
				slog.String("slug", container.Slug),
				slog.String("service", serviceName),
				slog.String("error", err.Error()))
			// Continue - container is removed but route may remain
		}
	}

	delete(m.containers, serviceName)

	m.logger.Info("Container deleted successfully",
		slog.String("container", container.Name),
		slog.String("service", serviceName))

	return nil
}

// GetRunningCount returns the number of running containers
func (m *Manager) GetRunningCount() int {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	count := 0
	for _, container := range m.containers {
		if container.Status == models.StatusRunning {
			count++
		}
	}
	return count
}

// getRunningCountUnsafe returns the number of running containers without locking
// IMPORTANT: This method is not thread-safe and should only be used when the caller
// already holds the mutex or when thread safety is not required (e.g., during validation)
// nolint:unused // May be used for debugging or future features
func (m *Manager) getRunningCountUnsafe() int {
	count := 0
	for _, container := range m.containers {
		if container.Status == models.StatusRunning {
			count++
		}
	}
	return count
}

// discoverContainers discovers existing containers managed by this service
func (m *Manager) discoverContainers(ctx context.Context) error {
	// List all containers with our prefix
	cmd := exec.CommandContext(ctx, "podman", "ps", "-a", "--format", "json")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("failed to list containers: %w", err)
	}

	if len(output) == 0 {
		return nil
	}

	var podmanContainers []map[string]interface{}
	if err := json.Unmarshal(output, &podmanContainers); err != nil {
		return fmt.Errorf("failed to parse container list: %w", err)
	}

	// Load Traefik configuration to find existing slugs
	traefikConfig, err := m.traefikManager.LoadConfig()
	if err != nil {
		m.logger.Warn("Failed to load Traefik config for slug discovery",
			slog.String("error", err.Error()))
		traefikConfig = nil
	}

	prefix := m.config.Container.NamePrefix
	for _, pc := range podmanContainers {
		names, ok := pc["Names"].([]interface{})
		if !ok || len(names) == 0 {
			continue
		}

		containerName, ok := names[0].(string)
		if !ok || !strings.HasPrefix(containerName, prefix) {
			continue
		}

		// Extract service name from container environment (original name)
		// First try to get original service name from environment variable
		originalServiceName := ""
		if inspectCmd := exec.CommandContext(ctx, "podman", "inspect", pc["Id"].(string), "--format", "{{.Config.Env}}"); inspectCmd != nil {
			if inspectOutput, err := inspectCmd.CombinedOutput(); err == nil {
				envStr := string(inspectOutput)
				if strings.Contains(envStr, "MCP_SERVICE_NAME=") {
					// Extract service name from environment variables
					if idx := strings.Index(envStr, "MCP_SERVICE_NAME="); idx != -1 {
						serviceNameStr := envStr[idx+len("MCP_SERVICE_NAME="):]
						if spaceIdx := strings.Index(serviceNameStr, " "); spaceIdx != -1 {
							serviceNameStr = serviceNameStr[:spaceIdx]
						}
						// Remove any quotes that might be present
						serviceNameStr = strings.Trim(serviceNameStr, "\"'")
						if serviceNameStr != "" {
							originalServiceName = serviceNameStr
						}
					}
				}
			}
		}

		// Fallback to sanitized name if we can't find the original
		serviceName := originalServiceName
		if serviceName == "" {
			serviceName = strings.TrimPrefix(containerName, prefix)
		}

		containerID := pc["Id"].(string)

		// Get container port from inspect
		port := 8000 // Default port
		if inspectCmd := exec.CommandContext(ctx, "podman", "inspect", containerID, "--format", "{{.Config.Env}}"); inspectCmd != nil {
			if inspectOutput, err := inspectCmd.CombinedOutput(); err == nil {
				envStr := string(inspectOutput)
				if strings.Contains(envStr, "MCP_CONTAINER_PORT=") {
					// Extract port from environment variables
					if idx := strings.Index(envStr, "MCP_CONTAINER_PORT="); idx != -1 {
						portStr := envStr[idx+len("MCP_CONTAINER_PORT="):]
						if spaceIdx := strings.Index(portStr, " "); spaceIdx != -1 {
							portStr = portStr[:spaceIdx]
						}
						if portStr != "" {
							if p, err := strconv.Atoi(portStr); err == nil {
								port = p
							}
						}
					}
				}
			}
		}

		// Try to find existing slug from Traefik configuration
		slug := m.findExistingSlugFromTraefik(serviceName, traefikConfig)
		if slug == "" {
			// Fallback to generating a new slug if not found in Traefik
			slug = generateSlug(serviceName)
			m.logger.Warn("Could not find existing slug in Traefik config, generating new one",
				slog.String("service", serviceName),
				slog.String("slug", slug))
		}

		container := &models.Container{
			ID:          containerID,
			Name:        containerName,
			ServiceName: serviceName,
			Slug:        slug,
			Image:       pc["Image"].(string),
			Status:      m.mapPodmanStatus(pc["State"].(string)),
			Port:        port,
			URL:         fmt.Sprintf("%s/mcp/%s", m.config.Traefik.ProxyHost, slug),
			Host:        m.config.Traefik.ProxyHost,
			CreatedAt:   time.Now(), // We don't have exact creation time
			UpdatedAt:   time.Now(),
		}

		// Store container using the original service name for lookup
		// This ensures health checks can find containers by their original name
		m.containers[serviceName] = container

		m.logger.Info("Discovered existing container with slug",
			slog.String("name", containerName),
			slog.String("service", serviceName),
			slog.String("slug", slug),
			slog.String("url", container.URL),
			slog.String("status", string(container.Status)))
	}

	return nil
}

// findExistingSlugFromTraefik finds the existing slug for a service from Traefik configuration
func (m *Manager) findExistingSlugFromTraefik(serviceName string, config *TraefikConfig) string {
	if config == nil || config.HTTP.Routers == nil {
		return ""
	}

	// Look for router names that match the pattern mcp-{service_name}-{hash}
	// The slug would be {service_name}-{hash}
	routerPrefix := fmt.Sprintf("mcp-%s-", serviceName)

	for routerName := range config.HTTP.Routers {
		if strings.HasPrefix(routerName, routerPrefix) {
			// Extract slug by removing the "mcp-" prefix
			slug := strings.TrimPrefix(routerName, "mcp-")
			m.logger.Info("Found existing slug from Traefik config",
				slog.String("service", serviceName),
				slog.String("router", routerName),
				slog.String("slug", slug))
			return slug
		}
	}

	return ""
}

// buildPodmanRunArgs builds the arguments for podman run command
func (m *Manager) buildPodmanRunArgs(container *models.Container) []string {
	args := []string{"run", "-d"}

	// Add name
	args = append(args, "--name", container.Name)

	// Add network (important for Traefik discovery)
	args = append(args, "--network", m.config.Traefik.Network)

	// No port mapping needed - Traefik will handle routing via path-based routing
	// The container will expose its internal port and Traefik will proxy to it

	// Add environment variables
	for key, value := range container.Environment {
		args = append(args, "-e", fmt.Sprintf("%s=%s", key, value))
	}

	// Add labels for automatic service discovery
	for key, value := range container.Labels {
		args = append(args, "--label", fmt.Sprintf("%s=%s", key, value))
	}

	// Add default resource limits
	if m.config.Container.DefaultMemoryLimit != "" {
		args = append(args, "--memory", m.config.Container.DefaultMemoryLimit)
	}

	if m.config.Container.DefaultCPULimit != "" {
		args = append(args, "--cpus", m.config.Container.DefaultCPULimit)
	}

	// Add image
	args = append(args, container.Image)

	// Add custom command if specified (this overrides the container's default CMD)
	if len(container.Command) > 0 {
		args = append(args, container.Command...)
	}

	return args
}

// waitForContainer waits for a container to be running
func (m *Manager) waitForContainer(ctx context.Context, containerID string) error {
	timeout := time.After(m.config.Container.StartupTimeout)
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timeout:
			return fmt.Errorf("timeout waiting for container to start")
		case <-ticker.C:
			cmd := exec.CommandContext(ctx, "podman", "inspect", containerID, "--format", "{{.State.Status}}")
			output, err := cmd.CombinedOutput()
			if err != nil {
				continue
			}

			status := strings.TrimSpace(string(output))
			if status == "running" {
				return nil
			}
			if status == "exited" || status == "dead" {
				return fmt.Errorf("container exited unexpectedly")
			}
		}
	}
}

// mapPodmanStatus maps Podman status to our container status
func (m *Manager) mapPodmanStatus(podmanStatus string) models.ContainerStatus {
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

// Helper functions
// nolint:unused // May be used for future features
func mergeLabels(template, request map[string]string) map[string]string {
	result := make(map[string]string)
	for k, v := range template {
		result[k] = v
	}
	for k, v := range request {
		result[k] = v
	}
	return result
}

// nolint:unused // May be used for future features
func mergeEnvironment(template, request map[string]string) map[string]string {
	result := make(map[string]string)
	for k, v := range template {
		result[k] = v
	}
	for k, v := range request {
		result[k] = v
	}
	return result
}

// getContainerIP retrieves the IP address of a container in the mcp-network
func (m *Manager) getContainerIP(ctx context.Context, containerID string) (string, error) {
	// Use a simpler approach to get container IP
	cmd := exec.CommandContext(ctx, "podman", "inspect", containerID)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("failed to inspect container: %w", err)
	}

	// Parse JSON to extract IP
	var inspectData []map[string]interface{}
	if err := json.Unmarshal(output, &inspectData); err != nil {
		return "", fmt.Errorf("failed to parse inspect output: %w", err)
	}

	if len(inspectData) == 0 {
		return "", fmt.Errorf("no container data found")
	}

	// Navigate to the IP address
	networkSettings, ok := inspectData[0]["NetworkSettings"].(map[string]interface{})
	if !ok {
		return "", fmt.Errorf("NetworkSettings not found")
	}

	networks, ok := networkSettings["Networks"].(map[string]interface{})
	if !ok {
		return "", fmt.Errorf("Networks not found")
	}

	mcpNetwork, ok := networks[m.config.Traefik.Network].(map[string]interface{})
	if !ok {
		return "", fmt.Errorf("network %s not found", m.config.Traefik.Network)
	}

	ipAddress, ok := mcpNetwork["IPAddress"].(string)
	if !ok || ipAddress == "" {
		return "", fmt.Errorf("IPAddress not found or empty")
	}

	return ipAddress, nil
}

// HandleMCPInstanceCreated handles the creation of an MCP server instance from domain events
func (m *Manager) HandleMCPInstanceCreated(ctx context.Context, instanceID, name string, jsonSpec map[string]interface{}) error {
	// Publish validating status
	if err := m.eventPublisher.PublishValidating(ctx, instanceID, name); err != nil {
		m.logger.Warn("Failed to publish validating status",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	}

	// Create MCP server instance model for validation (NO MUTEX LOCK YET)
	instance := &models.MCPServerInstance{
		InstanceID: instanceID,
		Name:       name,
		JSONSpec:   jsonSpec,
		Status:     "validating",
	}

	// Get current running count before validation (while unlocked)
	currentRunningCount := m.GetRunningCount()
	maxContainers := m.config.Container.MaxContainers

	// Perform comprehensive validation with image pulling (OUTSIDE MUTEX)
	validationResult, err := m.ValidateContainerSpecWithLimits(ctx, instance, true, currentRunningCount, maxContainers)
	if err != nil {
		m.logger.Error("Container validation failed",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
		return fmt.Errorf("container validation failed: %w", err)
	}

	if !validationResult.Valid {
		m.logger.Error("Container validation failed with errors",
			slog.String("instance_id", instanceID),
			slog.Any("errors", validationResult.Errors))

		// Publish failed status
		errorMsg := fmt.Sprintf("Validation failed: %v", validationResult.Errors)
		if err := m.eventPublisher.PublishFailed(ctx, instanceID, name, errorMsg); err != nil {
			m.logger.Warn("Failed to publish failed status",
				slog.String("instance_id", instanceID),
				slog.String("error", err.Error()))
		}

		return fmt.Errorf("container validation failed: %v", validationResult.Errors)
	}

	// Log warnings if any
	if len(validationResult.Warnings) > 0 {
		m.logger.Warn("Container validation completed with warnings",
			slog.String("instance_id", instanceID),
			slog.Any("warnings", validationResult.Warnings))
	}

	// Extract image (validated above)
	image, ok := jsonSpec["image"].(string)
	if !ok || image == "" {
		return fmt.Errorf("image is required in json_spec")
	}

	// Get container name for later use
	containerName := m.config.GetContainerName(name)

	// Extract container port (for internal use)
	containerPort := 8000 // Default MCP port
	if p, ok := jsonSpec["port"].(float64); ok {
		containerPort = int(p)
	} else if p, ok := jsonSpec["port"].(int); ok {
		containerPort = p
	}

	// Extract environment variables
	environment := make(map[string]string)
	if env, ok := jsonSpec["environment"].(map[string]interface{}); ok {
		for k, v := range env {
			if str, ok := v.(string); ok {
				environment[k] = str
			}
		}
	}

	// Extract custom command (optional)
	var command []string
	if cmdInterface, ok := jsonSpec["cmd"]; ok {
		if cmdSlice, ok := cmdInterface.([]interface{}); ok {
			for _, cmdItem := range cmdSlice {
				if cmdStr, ok := cmdItem.(string); ok {
					command = append(command, cmdStr)
				}
			}
		}
	}

	// Add MCP-specific environment variables
	environment["MCP_INSTANCE_ID"] = instanceID
	environment["MCP_SERVICE_NAME"] = name
	environment["MCP_CONTAINER_PORT"] = fmt.Sprintf("%d", containerPort)

	// NOW ACQUIRE MUTEX FOR CONTAINER OPERATIONS
	m.mutex.Lock()
	defer m.mutex.Unlock()

	// Check if container already exists
	if _, exists := m.containers[name]; exists {
		return fmt.Errorf("container %s already exists", name)
	}

	// Check container limit
	if len(m.containers) >= m.config.Container.MaxContainers {
		return fmt.Errorf("maximum container limit reached (%d)", m.config.Container.MaxContainers)
	}

	// Generate a unique slug for routing
	slug := generateSlug(name)

	// Create container with initial status
	container := &models.Container{
		Name:        containerName,
		ServiceName: name,
		Slug:        slug,
		Image:       image,
		Status:      models.StatusValidating,
		Port:        containerPort,
		URL:         fmt.Sprintf("%s/mcp/%s", m.config.Traefik.ProxyHost, slug), // External access via unified endpoint
		Host:        m.config.Traefik.ProxyHost,
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
		Labels:      make(map[string]string), // No labels needed for Traefik
		Environment: environment,
		Command:     command,
	}

	// Store container in tracking map with validating status
	m.containers[name] = container

	// Update status to starting
	container.Status = models.StatusStarting
	container.UpdatedAt = time.Now()

	// Publish starting status
	if err := m.eventPublisher.PublishStarting(ctx, instanceID, name); err != nil {
		m.logger.Warn("Failed to publish starting status",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	}

	m.logger.Info("Starting container creation",
		slog.String("container", containerName),
		slog.String("instance_id", instanceID),
		slog.String("image", image))

	// Build podman run command
	args := m.buildPodmanRunArgs(container)

	// Execute podman run
	cmd := exec.CommandContext(ctx, "podman", args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		container.Status = models.StatusError

		// Publish failed status
		errorMsg := fmt.Sprintf("Failed to create container: %v", err)
		if publishErr := m.eventPublisher.PublishFailed(ctx, instanceID, name, errorMsg); publishErr != nil {
			m.logger.Warn("Failed to publish failed status",
				slog.String("instance_id", instanceID),
				slog.String("error", publishErr.Error()))
		}

		m.logger.Error("Failed to create container",
			slog.String("container", containerName),
			slog.String("error", err.Error()),
			slog.String("output", string(output)))
		return fmt.Errorf("failed to create container: %w", err)
	}

	// Get container ID from output
	container.ID = strings.TrimSpace(string(output))

	// Wait for container to be running
	if err := m.waitForContainer(ctx, container.ID); err != nil {
		container.Status = models.StatusError

		// Publish failed status
		errorMsg := fmt.Sprintf("Container failed to start: %v", err)
		if publishErr := m.eventPublisher.PublishFailed(ctx, instanceID, name, errorMsg); publishErr != nil {
			m.logger.Warn("Failed to publish failed status",
				slog.String("instance_id", instanceID),
				slog.String("error", publishErr.Error()))
		}

		return fmt.Errorf("container failed to start: %w", err)
	}

	// Get container IP for Traefik routing
	containerIP, err := m.getContainerIP(ctx, container.ID)
	if err != nil {
		m.logger.Error("Failed to get container IP",
			slog.String("container", containerName),
			slog.String("error", err.Error()))
		// Continue without IP - container is still created
		containerIP = "127.0.0.1" // fallback
	}

	// Add Traefik route for the container using the slug
	if err := m.traefikManager.AddMCPService(ctx, slug, containerIP, containerPort); err != nil {
		m.logger.Error("Failed to add Traefik route",
			slog.String("slug", slug),
			slog.String("service", name),
			slog.String("error", err.Error()))
		// Continue - container is created but routing may not work
	}

	// Update final status and container info
	container.Status = models.StatusRunning
	container.UpdatedAt = time.Now()

	// Publish running status
	if err := m.eventPublisher.PublishRunning(ctx, instanceID, name, container.ID, container.URL); err != nil {
		m.logger.Warn("Failed to publish running status",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	}

	m.logger.Info("Container created successfully with Traefik routing",
		slog.String("container", containerName),
		slog.String("id", container.ID),
		slog.String("instance_id", instanceID),
		slog.String("url", container.URL),
		slog.String("container_ip", containerIP),
		slog.Int("container_port", containerPort),
		slog.Any("command", command),
		slog.String("final_status", string(container.Status)))

	return nil
}

// HandleMCPInstanceDeleted handles the deletion of an MCP server instance from domain events
func (m *Manager) HandleMCPInstanceDeleted(ctx context.Context, instanceID string) error {
	m.logger.Info("Handling MCP instance deletion",
		slog.String("instance_id", instanceID))

	// Find container by MCP instance ID
	containers := m.ListContainers()
	var targetContainer *models.Container

	for _, container := range containers {
		if container.Environment["MCP_INSTANCE_ID"] == instanceID {
			targetContainer = &container
			break
		}
	}

	if targetContainer == nil {
		m.logger.Warn("No container found for MCP instance",
			slog.String("instance_id", instanceID))
		return nil // Not an error - container might have been manually deleted
	}

	// Delete the container using existing functionality (includes Traefik route cleanup)
	err := m.DeleteContainer(ctx, targetContainer.ServiceName)
	if err != nil {
		m.logger.Error("Failed to delete MCP container",
			slog.String("instance_id", instanceID),
			slog.String("service_name", targetContainer.ServiceName),
			slog.String("error", err.Error()))
		return err
	}

	m.logger.Info("Successfully deleted MCP container",
		slog.String("instance_id", instanceID),
		slog.String("service_name", targetContainer.ServiceName))

	return nil
}

// generateSlug generates a URL-friendly slug from a name with a random suffix
func generateSlug(name string) string {
	// Convert to lowercase and replace spaces/special chars with hyphens
	slug := strings.ToLower(name)

	// Replace any non-alphanumeric characters with hyphens
	reg := regexp.MustCompile(`[^a-z0-9]+`)
	slug = reg.ReplaceAllString(slug, "-")

	// Remove leading/trailing hyphens
	slug = strings.Trim(slug, "-")

	// Add random suffix to ensure uniqueness
	randomBytes := make([]byte, 4)
	rand.Read(randomBytes)
	randomSuffix := hex.EncodeToString(randomBytes)

	return fmt.Sprintf("%s-%s", slug, randomSuffix)
}

// ValidateContainerSpec validates container specification before creation
func (m *Manager) ValidateContainerSpec(ctx context.Context, instance *models.MCPServerInstance, allowImagePull bool) (*ValidationResult, error) {
	m.logger.Info("Validating container specification",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name))

	// Use validator for dry-run validation
	result, err := m.validator.DryRunValidation(ctx, instance)
	if err != nil {
		m.logger.Error("Dry-run validation failed",
			slog.String("instance_id", instance.InstanceID),
			slog.String("error", err.Error()))
		return nil, fmt.Errorf("dry-run validation failed: %w", err)
	}

	// Additional image validation if requested
	if allowImagePull {
		image, ok := instance.JSONSpec["image"].(string)
		if ok && image != "" {
			imageResult, err := m.validator.ValidateContainerImage(ctx, image, allowImagePull)
			if err != nil {
				m.logger.Error("Image validation failed",
					slog.String("instance_id", instance.InstanceID),
					slog.String("image", image),
					slog.String("error", err.Error()))
				return nil, fmt.Errorf("image validation failed: %w", err)
			}

			// If image needs to be pulled, do it with progress tracking
			if !imageResult.ImageExists && imageResult.CanPull {
				m.logger.Info("Pulling required image",
					slog.String("instance_id", instance.InstanceID),
					slog.String("image", image))

				err = m.validator.PullImageWithProgress(ctx, image, func(progress string) {
					m.logger.Debug("Image pull progress",
						slog.String("instance_id", instance.InstanceID),
						slog.String("image", image),
						slog.String("progress", progress))
				})

				if err != nil {
					m.logger.Error("Failed to pull image",
						slog.String("instance_id", instance.InstanceID),
						slog.String("image", image),
						slog.String("error", err.Error()))
					return nil, fmt.Errorf("failed to pull image: %w", err)
				}
			}
		}
	}

	m.logger.Info("Container specification validation completed",
		slog.String("instance_id", instance.InstanceID),
		slog.Bool("valid", result.Valid),
		slog.Int("errors", len(result.Errors)),
		slog.Int("warnings", len(result.Warnings)))

	return result, nil
}

// ValidateContainerSpecWithLimits validates container specification with explicit container limits (deadlock-safe)
func (m *Manager) ValidateContainerSpecWithLimits(ctx context.Context, instance *models.MCPServerInstance, allowImagePull bool, currentRunningCount int, maxContainers int) (*ValidationResult, error) {
	m.logger.Info("Validating container specification with limits",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name),
		slog.Int("current_running", currentRunningCount),
		slog.Int("max_containers", maxContainers))

	// Use validator for dry-run validation (but avoid manager callbacks that cause deadlock)
	result, err := m.validator.DryRunValidationWithLimits(ctx, instance, currentRunningCount, maxContainers)
	if err != nil {
		m.logger.Error("Dry-run validation failed",
			slog.String("instance_id", instance.InstanceID),
			slog.String("error", err.Error()))
		return nil, fmt.Errorf("dry-run validation failed: %w", err)
	}

	// Additional image validation if requested
	if allowImagePull {
		image, ok := instance.JSONSpec["image"].(string)
		if ok && image != "" {
			imageResult, err := m.validator.ValidateContainerImage(ctx, image, allowImagePull)
			if err != nil {
				m.logger.Error("Image validation failed",
					slog.String("instance_id", instance.InstanceID),
					slog.String("image", image),
					slog.String("error", err.Error()))
				return nil, fmt.Errorf("image validation failed: %w", err)
			}

			// If image needs to be pulled, do it with progress tracking
			if !imageResult.ImageExists && imageResult.CanPull {
				m.logger.Info("Pulling required image",
					slog.String("instance_id", instance.InstanceID),
					slog.String("image", image))

				err = m.validator.PullImageWithProgress(ctx, image, func(progress string) {
					m.logger.Debug("Image pull progress",
						slog.String("instance_id", instance.InstanceID),
						slog.String("image", image),
						slog.String("progress", progress))
				})

				if err != nil {
					m.logger.Error("Failed to pull image",
						slog.String("instance_id", instance.InstanceID),
						slog.String("image", image),
						slog.String("error", err.Error()))
					return nil, fmt.Errorf("failed to pull image: %w", err)
				}
			}
		}
	}

	m.logger.Info("Container specification validation completed",
		slog.String("instance_id", instance.InstanceID),
		slog.Bool("valid", result.Valid),
		slog.Int("errors", len(result.Errors)),
		slog.Int("warnings", len(result.Warnings)))

	return result, nil
}

// startHealthMonitoring starts the background health monitoring system
func (m *Manager) startHealthMonitoring() {
	m.logger.Info("Starting background health monitoring")

	// Check health every 30 seconds
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	// Do initial health check
	m.performHealthCheckAll()

	for {
		select {
		case <-m.healthCtx.Done():
			m.logger.Info("Health monitoring stopped")
			return
		case <-ticker.C:
			m.performHealthCheckAll()
		}
	}
}

// performHealthCheckAll performs health checks on all containers
func (m *Manager) performHealthCheckAll() {
	m.mutex.RLock()
	containers := make([]*models.Container, 0, len(m.containers))
	for _, container := range m.containers {
		containers = append(containers, container)
	}
	m.mutex.RUnlock()

	if len(containers) == 0 {
		return
	}

	m.logger.Debug("Performing health checks on all containers",
		slog.Int("container_count", len(containers)))

	// Perform health checks
	for _, container := range containers {
		// Create a timeout context for each health check
		healthCtx, cancel := context.WithTimeout(m.healthCtx, 15*time.Second)

		result, err := m.healthChecker.PerformHealthCheck(healthCtx, container)
		if err != nil {
			m.logger.Error("Health check failed",
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

		// Update health status
		m.updateContainerHealth(container, result)
		cancel()
	}
}

// updateContainerHealth updates the health status of a container
func (m *Manager) updateContainerHealth(container *models.Container, result *HealthCheckResult) {
	m.mutex.Lock()
	defer m.mutex.Unlock()

	// Store health result
	m.containerHealth[container.Name] = result

	// Update container status based on health
	previousStatus := container.Status
	newStatus := m.determineContainerStatus(result)

	if newStatus != previousStatus {
		container.Status = newStatus
		container.UpdatedAt = time.Now()

		m.logger.Info("Container health status changed",
			slog.String("container", container.Name),
			slog.String("previous_status", string(previousStatus)),
			slog.String("new_status", string(newStatus)),
			slog.Bool("healthy", result.Healthy),
			slog.Bool("http_reachable", result.HTTPReachable))

		// Publish status change event if needed
		if instanceID, exists := container.Environment["MCP_INSTANCE_ID"]; exists {
			go func() {
				var publishErr error
				switch newStatus {
				case models.StatusRunning:
					publishErr = m.eventPublisher.PublishRunning(m.healthCtx, instanceID, container.ServiceName, container.ID, container.URL)
				case models.StatusError:
					publishErr = m.eventPublisher.PublishFailed(m.healthCtx, instanceID, container.ServiceName, result.Error)
				case models.StatusStopped:
					publishErr = m.eventPublisher.PublishStatusUpdate(m.healthCtx, instanceID, container.ServiceName, "stopped", container.ID, "")
				}

				if publishErr != nil {
					m.logger.Warn("Failed to publish status change event",
						slog.String("instance_id", instanceID),
						slog.String("container", container.Name),
						slog.String("error", publishErr.Error()))
				}
			}()
		}
	}
}

// determineContainerStatus determines the container status based on health check result
func (m *Manager) determineContainerStatus(result *HealthCheckResult) models.ContainerStatus {
	if result.Healthy && result.HTTPReachable {
		return models.StatusRunning
	}

	if result.Status == models.StatusStopped {
		return models.StatusStopped
	}

	if result.Error != "" {
		return models.StatusError
	}

	return result.Status
}

// GetContainerHealthStatus returns the health status of a container
func (m *Manager) GetContainerHealthStatus(serviceName string) (*HealthCheckResult, bool) {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	containerName := m.config.GetContainerName(serviceName)
	healthResult, exists := m.containerHealth[containerName]
	return healthResult, exists
}

// Shutdown gracefully shuts down the container manager
func (m *Manager) Shutdown(ctx context.Context) error {
	m.logger.Info("Shutting down container manager")

	// Cancel health monitoring
	if m.healthCancel != nil {
		m.healthCancel()
	}

	// Wait for health monitoring to stop or timeout
	select {
	case <-ctx.Done():
		m.logger.Warn("Shutdown timeout reached")
	case <-time.After(5 * time.Second):
		m.logger.Info("Container manager shutdown complete")
	}

	return nil
}

// autoRestartContainers checks for containers that should be running and restarts them if needed
func (m *Manager) autoRestartContainers(ctx context.Context) error {
	m.mutex.Lock()
	defer m.mutex.Unlock()

	containersToRestart := []*models.Container{}

	// Find containers that should be running but are stopped
	for _, container := range m.containers {
		// Check real-time status
		realStatus := m.getRealTimeContainerStatus(ctx, container)

		if realStatus == models.StatusStopped && m.shouldContainerBeRunning(container) {
			containersToRestart = append(containersToRestart, container)
		}
	}

	if len(containersToRestart) == 0 {
		m.logger.Info("No containers need to be restarted")
		return nil
	}

	m.logger.Info("Auto-restarting stopped containers",
		slog.Int("count", len(containersToRestart)))

	// Restart containers
	for _, container := range containersToRestart {
		if err := m.restartContainer(ctx, container); err != nil {
			m.logger.Error("Failed to restart container",
				slog.String("container", container.Name),
				slog.String("error", err.Error()))
			continue
		}

		m.logger.Info("Successfully restarted container",
			slog.String("container", container.Name),
			slog.String("service", container.ServiceName))
	}

	return nil
}

// shouldContainerBeRunning determines if a container should be running based on its metadata
func (m *Manager) shouldContainerBeRunning(container *models.Container) bool {
	// For now, assume all discovered containers should be running
	// In a more sophisticated system, this could check database state,
	// environment variables, or other metadata to determine desired state
	_ = container // Parameter may be used in future implementations
	return true
}

// getRealTimeContainerStatus gets the real-time status from Podman
func (m *Manager) getRealTimeContainerStatus(ctx context.Context, container *models.Container) models.ContainerStatus {
	if container.ID == "" {
		return models.StatusError
	}

	cmd := exec.CommandContext(ctx, "podman", "inspect", container.ID, "--format", "{{.State.Status}}")
	output, err := cmd.CombinedOutput()
	if err != nil {
		m.logger.Debug("Failed to get real-time container status",
			slog.String("container", container.Name),
			slog.String("error", err.Error()))
		return models.StatusError
	}

	podmanStatus := strings.TrimSpace(string(output))
	return m.mapPodmanStatus(podmanStatus)
}

// restartContainer restarts a stopped container
func (m *Manager) restartContainer(ctx context.Context, container *models.Container) error {
	m.logger.Info("Restarting container",
		slog.String("container", container.Name),
		slog.String("service", container.ServiceName))

	// Update status to starting
	container.Status = models.StatusStarting
	container.UpdatedAt = time.Now()

	// Start the container
	cmd := exec.CommandContext(ctx, "podman", "start", container.ID)
	output, err := cmd.CombinedOutput()
	if err != nil {
		container.Status = models.StatusError
		return fmt.Errorf("failed to start container: %w, output: %s", err, string(output))
	}

	// Wait for container to be running
	if err := m.waitForContainer(ctx, container.ID); err != nil {
		container.Status = models.StatusError
		return fmt.Errorf("container failed to start properly: %w", err)
	}

	// Get container IP for Traefik routing (in case it changed)
	containerIP, err := m.getContainerIP(ctx, container.ID)
	if err != nil {
		m.logger.Error("Failed to get container IP after restart",
			slog.String("container", container.Name),
			slog.String("error", err.Error()))
		// Continue - container is started but routing may not work
		containerIP = "127.0.0.1" // fallback
	}

	// Update/refresh Traefik route for the container
	if container.Slug != "" {
		if err := m.traefikManager.AddMCPService(ctx, container.Slug, containerIP, container.Port); err != nil {
			m.logger.Error("Failed to update Traefik route after restart",
				slog.String("slug", container.Slug),
				slog.String("service", container.ServiceName),
				slog.String("error", err.Error()))
			// Continue - container is running but routing may not work
		}
	}

	// Update final status
	container.Status = models.StatusRunning
	container.UpdatedAt = time.Now()

	// Publish running status if we have instance ID
	if instanceID, exists := container.Environment["MCP_INSTANCE_ID"]; exists {
		if err := m.eventPublisher.PublishRunning(ctx, instanceID, container.ServiceName, container.ID, container.URL); err != nil {
			m.logger.Warn("Failed to publish running status after restart",
				slog.String("instance_id", instanceID),
				slog.String("error", err.Error()))
		}
	}

	return nil
}

// syncWithCoreAPI synchronizes with the Core API to handle pending instances
func (m *Manager) syncWithCoreAPI(ctx context.Context) error {
	m.logger.Info("Starting synchronization with Core API")

	// Get all MCP instances from Core API
	url := fmt.Sprintf("%s/v1/mcp-server-instances/", m.config.CoreAPIURL)
	m.logger.Info("Fetching MCP instances from Core API", slog.String("url", url))

	// Create HTTP client with timeout
	client := &http.Client{
		Timeout: 10 * time.Second,
	}

	resp, err := client.Get(url)
	if err != nil {
		return fmt.Errorf("failed to fetch MCP instances: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return fmt.Errorf("Core API returned status %d", resp.StatusCode)
	}

	var instances []models.MCPServerInstance
	if err := json.NewDecoder(resp.Body).Decode(&instances); err != nil {
		return fmt.Errorf("failed to decode instances response: %w", err)
	}

	m.logger.Info("Fetched MCP instances from Core API",
		slog.Int("total_instances", len(instances)))

	// Process each instance
	pendingCount := 0
	for _, instance := range instances {
		m.logger.Info("Processing instance",
			slog.String("instance_id", instance.InstanceID),
			slog.String("name", instance.Name),
			slog.String("status", instance.Status))

		// Check if instance should have a container but doesn't exist
		if instance.Status == "pending" || instance.Status == "starting" {
			// Check if container already exists
			if _, exists := m.containers[instance.Name]; !exists {
				m.logger.Info("Creating missing container for pending instance",
					slog.String("instance_id", instance.InstanceID),
					slog.String("name", instance.Name))

				// Extract image and port from JSONSpec
				image, imageOk := instance.JSONSpec["image"].(string)
				portFloat, portOk := instance.JSONSpec["port"].(float64)
				port := int(portFloat)

				if !imageOk || !portOk {
					m.logger.Error("Invalid JSON spec for instance",
						slog.String("instance_id", instance.InstanceID),
						slog.String("error", "missing image or port"))
					continue
				}

				// Extract environment variables
				environment := make(map[string]string)
				if envMap, ok := instance.JSONSpec["environment"].(map[string]interface{}); ok {
					for k, v := range envMap {
						if strVal, ok := v.(string); ok {
							environment[k] = strVal
						}
					}
				}

				// Add MCP instance ID to environment for tracking
				environment["MCP_INSTANCE_ID"] = instance.InstanceID

				// Create container request
				req := models.CreateContainerRequest{
					ServiceName: instance.Name,
					Image:       image,
					Port:        port,
					Environment: environment,
				}

				// Create container
				if _, err := m.CreateContainer(ctx, req); err != nil {
					m.logger.Error("Failed to create container for pending instance",
						slog.String("instance_id", instance.InstanceID),
						slog.String("name", instance.Name),
						slog.String("error", err.Error()))
				} else {
					m.logger.Info("Successfully created container for pending instance",
						slog.String("instance_id", instance.InstanceID),
						slog.String("name", instance.Name))
				}
				pendingCount++
			}
		}
	}

	m.logger.Info("Core API synchronization completed",
		slog.Int("total_instances", len(instances)),
		slog.Int("pending_processed", pendingCount))

	return nil
}
