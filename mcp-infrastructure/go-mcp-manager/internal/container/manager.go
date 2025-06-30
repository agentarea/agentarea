package container

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"os/exec"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

// Manager manages container lifecycle using Podman
type Manager struct {
	config         *config.Config
	containers     map[string]*models.Container
	mutex          sync.RWMutex
	logger         *slog.Logger
	traefikManager *TraefikManager
}

// NewManager creates a new container manager
func NewManager(cfg *config.Config, logger *slog.Logger) *Manager {
	return &Manager{
		config:         cfg,
		containers:     make(map[string]*models.Container),
		logger:         logger,
		traefikManager: NewTraefikManager(logger),
	}
}

// Initialize initializes the container manager
func (m *Manager) Initialize(ctx context.Context) error {
	m.logger.Info("Initializing container manager")

	// Discover existing containers
	if err := m.discoverContainers(ctx); err != nil {
		m.logger.Error("Failed to discover existing containers", slog.String("error", err.Error()))
		return err
	}

	m.logger.Info("Container manager initialized successfully",
		slog.Int("existing_containers", len(m.containers)))

	return nil
}

// CreateContainer creates a new container from a template
func (m *Manager) CreateContainer(ctx context.Context, req models.CreateContainerRequest) (*models.Container, error) {
	m.mutex.Lock()
	defer m.mutex.Unlock()

	// Check if container already exists
	containerName := m.config.GetContainerName(req.ServiceName)
	if _, exists := m.containers[containerName]; exists {
		return nil, fmt.Errorf("container %s already exists", containerName)
	}

	// Check container limit
	if len(m.containers) >= m.config.Container.MaxContainers {
		return nil, fmt.Errorf("maximum container limit reached (%d)", m.config.Container.MaxContainers)
	}

	// Create container directly from request
	container := &models.Container{
		Name:        containerName,
		ServiceName: req.ServiceName,
		Image:       req.Image,
		Status:      models.StatusStarting,
		Port:        req.Port,
		URL:         m.config.GetServiceURL(req.ServiceName, req.Port),
		Host:        m.config.GetServiceHost(req.ServiceName),
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

	// Add Traefik route for the container
	if err := m.traefikManager.AddMCPService(ctx, req.ServiceName, containerIP, req.Port); err != nil {
		m.logger.Error("Failed to add Traefik route",
			slog.String("service", req.ServiceName),
			slog.String("error", err.Error()))
		// Continue - container is created but routing may not work
	}

	container.Status = models.StatusRunning
	m.containers[containerName] = container

	m.logger.Info("Container created successfully",
		slog.String("container", containerName),
		slog.String("id", container.ID),
		slog.String("service", req.ServiceName),
		slog.String("container_ip", containerIP))

	return container, nil
}

// GetContainer gets a container by service name
func (m *Manager) GetContainer(serviceName string) (*models.Container, error) {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	containerName := m.config.GetContainerName(serviceName)
	container, exists := m.containers[containerName]
	if !exists {
		return nil, fmt.Errorf("container %s not found", containerName)
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

	containerName := m.config.GetContainerName(serviceName)
	container, exists := m.containers[containerName]
	if !exists {
		return models.StatusError, fmt.Errorf("container %s not found", containerName)
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

	containerName := m.config.GetContainerName(serviceName)
	_, exists := m.containers[containerName]
	if !exists {
		return nil, fmt.Errorf("container %s not found", containerName)
	}

	// First check if container is running
	status, err := m.GetContainerStatus(ctx, serviceName)
	if err != nil {
		return nil, err
	}

	result := map[string]interface{}{
		"container_status": string(status),
		"timestamp":        time.Now(),
		"service_name":     serviceName,
	}

	if status != models.StatusRunning {
		result["healthy"] = false
		result["reason"] = "container not running"
		return result, nil
	}

	// TODO: Perform actual HTTP health check
	// For now, just return that container is running
	result["healthy"] = true
	result["reason"] = "container is running"

	return result, nil
}

// DeleteContainer stops and removes a container
func (m *Manager) DeleteContainer(ctx context.Context, serviceName string) error {
	m.mutex.Lock()
	defer m.mutex.Unlock()

	containerName := m.config.GetContainerName(serviceName)
	container, exists := m.containers[containerName]
	if !exists {
		return fmt.Errorf("container %s not found", containerName)
	}

	container.Status = models.StatusStopping

	// Stop container
	stopCmd := exec.CommandContext(ctx, "podman", "stop", container.ID)
	if output, err := stopCmd.CombinedOutput(); err != nil {
		m.logger.Error("Failed to stop container",
			slog.String("container", containerName),
			slog.String("error", err.Error()),
			slog.String("output", string(output)))
	}

	// Remove container
	rmCmd := exec.CommandContext(ctx, "podman", "rm", container.ID)
	if output, err := rmCmd.CombinedOutput(); err != nil {
		m.logger.Error("Failed to remove container",
			slog.String("container", containerName),
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

	delete(m.containers, containerName)

	m.logger.Info("Container deleted successfully",
		slog.String("container", containerName),
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

		// Extract service name
		serviceName := strings.TrimPrefix(containerName, prefix)

		container := &models.Container{
			ID:          pc["Id"].(string),
			Name:        containerName,
			ServiceName: serviceName,
			Image:       pc["Image"].(string),
			Status:      m.mapPodmanStatus(pc["State"].(string)),
			CreatedAt:   time.Now(), // We don't have exact creation time
			UpdatedAt:   time.Now(),
		}

		m.containers[containerName] = container

		m.logger.Info("Discovered existing container",
			slog.String("name", containerName),
			slog.String("service", serviceName),
			slog.String("status", string(container.Status)))
	}

	return nil
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
	m.mutex.Lock()
	defer m.mutex.Unlock()

	// Check if container already exists
	containerName := m.config.GetContainerName(name)
	if _, exists := m.containers[containerName]; exists {
		return fmt.Errorf("container %s already exists", containerName)
	}

	// Extract image (required)
	image, ok := jsonSpec["image"].(string)
	if !ok || image == "" {
		return fmt.Errorf("image is required in json_spec")
	}

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

	// Check container limit
	if len(m.containers) >= m.config.Container.MaxContainers {
		return fmt.Errorf("maximum container limit reached (%d)", m.config.Container.MaxContainers)
	}

	// Generate a unique slug for routing
	slug := generateSlug(name)

	// Create container
	container := &models.Container{
		Name:        containerName,
		ServiceName: name,
		Slug:        slug,
		Image:       image,
		Status:      models.StatusStarting,
		Port:        containerPort,
		URL:         fmt.Sprintf("%s/mcp/%s", m.config.Traefik.ProxyHost, slug), // External access via unified endpoint
		Host:        m.config.Traefik.ProxyHost,
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
		Labels:      make(map[string]string), // No labels needed for Traefik
		Environment: environment,
		Command:     command,
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
		return fmt.Errorf("failed to create container: %w", err)
	}

	// Get container ID from output
	container.ID = strings.TrimSpace(string(output))

	// Wait for container to be running
	if err := m.waitForContainer(ctx, container.ID); err != nil {
		container.Status = models.StatusError
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

	container.Status = models.StatusRunning
	m.containers[containerName] = container

	m.logger.Info("Container created successfully with Traefik routing",
		slog.String("container", containerName),
		slog.String("id", container.ID),
		slog.String("instance_id", instanceID),
		slog.String("url", container.URL),
		slog.String("container_ip", containerIP),
		slog.Int("container_port", containerPort),
		slog.Any("command", command))

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
