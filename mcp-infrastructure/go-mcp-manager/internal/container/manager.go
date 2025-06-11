package container

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

// Manager manages container lifecycle using Podman
type Manager struct {
	config     *config.Config
	containers map[string]*models.Container
	templates  map[string]*models.Template
	mutex      sync.RWMutex
	logger     *slog.Logger
}

// NewManager creates a new container manager
func NewManager(cfg *config.Config, logger *slog.Logger) *Manager {
	return &Manager{
		config:     cfg,
		containers: make(map[string]*models.Container),
		templates:  make(map[string]*models.Template),
		logger:     logger,
	}
}

// Initialize initializes the container manager
func (m *Manager) Initialize(ctx context.Context) error {
	// Load templates
	if err := m.loadTemplates(); err != nil {
		return fmt.Errorf("failed to load templates: %w", err)
	}

	// Discover existing containers
	if err := m.discoverContainers(ctx); err != nil {
		return fmt.Errorf("failed to discover containers: %w", err)
	}

	m.logger.Info("Container manager initialized",
		slog.Int("templates", len(m.templates)),
		slog.Int("containers", len(m.containers)))

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

	// Get template
	template, exists := m.templates[req.Template]
	if !exists {
		return nil, fmt.Errorf("template %s not found", req.Template)
	}

	// Check container limit
	if len(m.containers) >= m.config.Container.MaxContainers {
		return nil, fmt.Errorf("maximum container limit reached (%d)", m.config.Container.MaxContainers)
	}

	// Create container
	container := &models.Container{
		Name:        containerName,
		ServiceName: req.ServiceName,
		Image:       template.Image,
		Status:      models.StatusStarting,
		Port:        template.Port,
		URL:         m.config.GetServiceURL(req.ServiceName, template.Port),
		Host:        m.config.GetServiceHost(req.ServiceName),
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
		Labels:      mergeLabels(template.Labels, req.Labels),
		Environment: mergeEnvironment(template.Environment, req.Environment),
	}

	// Build podman run command
	args := m.buildPodmanRunArgs(container, template)

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

	container.Status = models.StatusRunning
	m.containers[containerName] = container

	m.logger.Info("Container created successfully",
		slog.String("container", containerName),
		slog.String("id", container.ID),
		slog.String("service", req.ServiceName))

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

// ListTemplates returns all available templates
func (m *Manager) ListTemplates() []models.Template {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	templates := make([]models.Template, 0, len(m.templates))
	for _, template := range m.templates {
		templates = append(templates, *template)
	}

	return templates
}

// loadTemplates loads container templates from the templates directory
func (m *Manager) loadTemplates() error {
	templatesDir := m.config.Container.TemplatesDir
	if _, err := os.Stat(templatesDir); os.IsNotExist(err) {
		m.logger.Warn("Templates directory does not exist", slog.String("dir", templatesDir))
		return nil
	}

	entries, err := os.ReadDir(templatesDir)
	if err != nil {
		return err
	}

	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}

		templatePath := filepath.Join(templatesDir, entry.Name())
		template, err := m.loadTemplate(templatePath)
		if err != nil {
			m.logger.Error("Failed to load template",
				slog.String("file", templatePath),
				slog.String("error", err.Error()))
			continue
		}

		templateName := strings.TrimSuffix(entry.Name(), ".json")
		template.Name = templateName
		m.templates[templateName] = template

		m.logger.Debug("Loaded template",
			slog.String("name", templateName),
			slog.String("image", template.Image))
	}

	return nil
}

// loadTemplate loads a single template from a JSON file
func (m *Manager) loadTemplate(path string) (*models.Template, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var template models.Template
	if err := json.Unmarshal(data, &template); err != nil {
		return nil, err
	}

	return &template, nil
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

	prefix := m.config.Container.Prefix
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
	}

	return nil
}

// buildPodmanRunArgs builds the arguments for podman run command
func (m *Manager) buildPodmanRunArgs(container *models.Container, template *models.Template) []string {
	args := []string{"run", "-d"}

	// Add name
	args = append(args, "--name", container.Name)

	// Add port mapping
	if template.Port > 0 {
		args = append(args, "-p", fmt.Sprintf("%d:%d", template.Port, template.Port))
	}

	// Add environment variables
	for key, value := range container.Environment {
		args = append(args, "-e", fmt.Sprintf("%s=%s", key, value))
	}

	// Add labels
	for key, value := range container.Labels {
		args = append(args, "--label", fmt.Sprintf("%s=%s", key, value))
	}

	// Add resource limits
	if template.MemoryLimit != "" {
		args = append(args, "--memory", template.MemoryLimit)
	} else if m.config.Container.DefaultMemoryLimit != "" {
		args = append(args, "--memory", m.config.Container.DefaultMemoryLimit)
	}

	if template.CPULimit != "" {
		args = append(args, "--cpus", template.CPULimit)
	} else if m.config.Container.DefaultCPULimit != "" {
		args = append(args, "--cpus", m.config.Container.DefaultCPULimit)
	}

	// Add volumes
	for _, volume := range template.Volumes {
		volumeArg := fmt.Sprintf("%s:%s", volume.Source, volume.Destination)
		if volume.ReadOnly {
			volumeArg += ":ro"
		}
		args = append(args, "-v", volumeArg)
	}

	// Add image
	args = append(args, template.Image)

	// Add command
	if len(template.Command) > 0 {
		args = append(args, template.Command...)
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
