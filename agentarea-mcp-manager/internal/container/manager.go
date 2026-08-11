package container

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/database"
	"github.com/agentarea/mcp-manager/internal/events"
	"github.com/agentarea/mcp-manager/internal/models"
	_ "github.com/jackc/pgx/v5/stdlib"
)

// SecretResolverInterface allows the manager to resolve secrets without importing the secrets package directly
type SecretResolverInterface interface {
	ResolveInstanceEnvVars(instanceID string, envVarNames []string) (map[string]string, error)
}

// Manager manages container lifecycle for MCP servers
type Manager struct {
	config          *config.Config
	containers      map[string]*models.Container
	containerHealth map[string]*HealthCheckResult // Track health status
	mutex           sync.RWMutex
	logger          *slog.Logger
	validator       *ContainerValidator
	healthChecker   *HealthChecker
	eventPublisher  *events.EventPublisher
	healthCtx       context.Context
	healthCancel    context.CancelFunc
	secretResolver  SecretResolverInterface // Optional: resolves secrets from encrypted_secrets table
}

// NewManager creates a new container manager
func NewManager(cfg *config.Config, logger *slog.Logger) *Manager {
	healthChecker := NewHealthChecker(cfg, logger)
	eventPublisher := events.NewEventPublisher(cfg.Redis.URL, logger)

	// Create context for health monitoring
	healthCtx, healthCancel := context.WithCancel(context.Background())

	manager := &Manager{
		config:          cfg,
		containers:      make(map[string]*models.Container),
		containerHealth: make(map[string]*HealthCheckResult),
		logger:          logger,
		healthChecker:   healthChecker,
		eventPublisher:  eventPublisher,
		healthCtx:       healthCtx,
		healthCancel:    healthCancel,
	}

	// Create validator with manager reference (after manager is created)
	manager.validator = NewContainerValidator(logger, manager, cfg.Container.Runtime)

	return manager
}

// SetSecretResolver sets the secret resolver for resolving env vars from encrypted_secrets table
func (m *Manager) SetSecretResolver(resolver SecretResolverInterface) {
	m.secretResolver = resolver
}

// ResolveSecretEnvVars resolves the secret env vars named in json_spec["env_vars"]
// from the encrypted_secrets table. These are secret values stripped out of
// json_spec.environment at create time (only the names travel in the spec); the
// values are decrypted here from the DB and never sent over the wire.
//
// Returns an empty map when no resolver is configured or no secret names are
// present. This is the single source of secret resolution shared by the HTTP
// create path (which owns provisioning) and the DB-sync reconcile loop.
func (m *Manager) ResolveSecretEnvVars(instanceID string, jsonSpec map[string]interface{}) map[string]string {
	resolved := make(map[string]string)
	if m.secretResolver == nil || jsonSpec == nil {
		return resolved
	}
	envVarsRaw, ok := jsonSpec["env_vars"].([]interface{})
	if !ok || len(envVarsRaw) == 0 {
		return resolved
	}
	envVarNames := make([]string, 0, len(envVarsRaw))
	for _, v := range envVarsRaw {
		if name, ok := v.(string); ok {
			envVarNames = append(envVarNames, name)
		}
	}
	if len(envVarNames) == 0 {
		return resolved
	}
	secretEnvVars, err := m.secretResolver.ResolveInstanceEnvVars(instanceID, envVarNames)
	if err != nil {
		m.logger.Error("Failed to resolve secret env vars",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
		return resolved
	}
	if len(secretEnvVars) > 0 {
		m.logger.Info("Resolved secret env vars from encrypted_secrets",
			slog.String("instance_id", instanceID),
			slog.Int("count", len(secretEnvVars)))
	}
	return secretEnvVars
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

	// Skip Core API sync if SKIP_INSTANCE_SYNC is set (useful for dev)
	if os.Getenv("SKIP_INSTANCE_SYNC") != "true" {
		// Synchronize with Core API to handle pending instances
		m.logger.Info("Starting Core API synchronization...")
		if err := m.syncWithCoreAPI(ctx); err != nil {
			m.logger.Error("Failed to sync with Core API", slog.String("error", err.Error()))
			// Don't fail initialization - log warning and continue
			m.logger.Warn("Continuing without full sync - some instances may need manual intervention")
		}
		m.logger.Info("Core API synchronization completed")
	} else {
		m.logger.Info("Skipping Core API synchronization (SKIP_INSTANCE_SYNC=true)")
	}

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
		URL:         fmt.Sprintf("/mcp/%s", slug),
		Host:        containerName,
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
		Labels:      req.Labels,
		Environment: req.Environment,
		Command:     req.Command,
		Isolation:   req.Isolation,
		MemoryLimit: req.MemoryLimit,
		CPULimit:    req.CPULimit,
	}

	// Refuse rather than silently downgrade: starting third-party code without
	// the isolation it was assigned is worse than not starting it.
	if err := m.ensureRuntimeAvailable(ctx, container.Isolation); err != nil {
		return nil, err
	}

	// A leftover container from an earlier attempt holds the name this run needs.
	if err := m.clearContainerName(ctx, container.Name); err != nil {
		return nil, err
	}

	// Build container run command (Traefik labels are added automatically)
	args := m.buildContainerRunArgs(container)

	// Execute runtime run
	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		container.Status = models.StatusError
		m.logger.Error("Failed to create container",
			slog.String("container", containerName),
			slog.String("error", err.Error()),
			slog.String("output", string(output)))
		return nil, fmt.Errorf("failed to create container: %s", runtimeRefusal(output))
	}

	// Get container ID from output
	container.ID = strings.TrimSpace(string(output))

	// Wait for container to be running
	if err := m.waitForContainer(ctx, container.ID); err != nil {
		container.Status = models.StatusError
		// No caller ever receives a handle to this container, and it was never
		// recorded, so nothing can reclaim it later: it would sit dead on the
		// host holding its name and its disk, unknown to the control plane.
		// What it printed is the only record of why it stopped, so that is kept
		// before the corpse goes.
		m.logger.Error("Container exited before it could serve",
			slog.String("container", containerName),
			slog.String("id", container.ID),
			slog.String("output", m.containerOutput(ctx, container.ID)))
		if reapErr := m.clearContainerName(ctx, container.Name); reapErr != nil {
			m.logger.Warn("Could not remove the container that failed to start",
				slog.String("container", containerName),
				slog.String("error", reapErr.Error()))
		}
		return nil, fmt.Errorf("container failed to start: %w", err)
	}

	container.Status = models.StatusRunning
	m.containers[req.ServiceName] = container

	m.logger.Info("Container created successfully",
		slog.String("container", containerName),
		slog.String("id", container.ID),
		slog.String("service", req.ServiceName),
		slog.String("slug", slug),
		slog.String("url", container.URL))

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
// StartContainer starts a container that exists but is stopped.
//
// Separate from CreateContainer because an idle-reclaimed instance still has
// its container, with its image, environment and isolation already settled.
// Recreating it would re-resolve all of that and could quietly produce a
// different container than the one that was reclaimed.
func (m *Manager) StartContainer(ctx context.Context, serviceName string) error {
	managed, err := m.GetContainer(serviceName)
	if err != nil {
		return err
	}

	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, "start", managed.ID)
	if output, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("starting %s: %w: %s", serviceName, err, strings.TrimSpace(string(output)))
	}
	return nil
}

// ContainerAddress returns host:port for reaching a container from this host.
//
// Resolved on every call rather than cached: Docker assigns a new IP when a
// container restarts, and a stale address silently routes traffic to whichever
// container took it over.
func (m *Manager) ContainerAddress(ctx context.Context, serviceName string) (string, error) {
	managed, err := m.GetContainer(serviceName)
	if err != nil {
		return "", err
	}

	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, "inspect", managed.ID,
		"--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}")
	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("inspecting %s for its address: %w", serviceName, err)
	}

	address := strings.TrimSpace(string(output))
	if address == "" {
		return "", fmt.Errorf("container %s has no network address yet", serviceName)
	}
	return net.JoinHostPort(address, strconv.Itoa(managed.Port)), nil
}

func (m *Manager) GetContainerStatus(ctx context.Context, serviceName string) (models.ContainerStatus, error) {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	container, exists := m.containers[serviceName]
	if !exists {
		return models.StatusError, fmt.Errorf("container %s not found", serviceName)
	}

	// Get real-time status from runtime
	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, "inspect", container.ID, "--format", "{{.State.Status}}")
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

	// Stopping is best effort: a container that already exited, or that the host
	// reaped, cannot be stopped, and neither is a reason to keep the record.
	stopCmd := exec.CommandContext(ctx, m.config.Container.Runtime, "stop", container.ID)
	if output, err := stopCmd.CombinedOutput(); err != nil {
		m.logger.Error("Failed to stop container",
			slog.String("container", container.Name),
			slog.String("error", err.Error()),
			slog.String("output", string(output)))
	}

	// A container that is no longer there is the state the caller asked for, so
	// removal is idempotent. Without this, a container reaped out of band -- by
	// a host cleanup, or a runtime restart -- left a record that nothing could
	// ever delete: every retirement failed on the missing container and the
	// instance stayed in the control plane for good.
	rmCmd := exec.CommandContext(ctx, m.config.Container.Runtime, "rm", "-f", container.ID)
	if output, err := rmCmd.CombinedOutput(); err != nil && !containerAlreadyGone(output) {
		m.logger.Error("Failed to remove container",
			slog.String("container", container.Name),
			slog.String("error", err.Error()),
			slog.String("output", string(output)))
		return fmt.Errorf("failed to remove container: %w", err)
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
// containerEnvironment reads a container's environment as a map.
//
// Discovery previously scraped this output with substring searches for two
// specific variables. Parsing it once, properly, is what lets a rediscovered
// container answer lookups by instance id.
func (m *Manager) containerEnvironment(ctx context.Context, containerID string) map[string]string {
	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, "inspect", containerID,
		"--format", "{{json .Config.Env}}")
	output, err := cmd.Output()
	if err != nil {
		m.logger.Warn("Failed to read container environment",
			slog.String("container_id", containerID),
			slog.String("error", err.Error()))
		return nil
	}

	var entries []string
	if err := json.Unmarshal(output, &entries); err != nil {
		m.logger.Warn("Failed to parse container environment",
			slog.String("container_id", containerID),
			slog.String("error", err.Error()))
		return nil
	}

	environment := make(map[string]string, len(entries))
	for _, entry := range entries {
		if name, value, found := strings.Cut(entry, "="); found {
			environment[name] = value
		}
	}
	return environment
}

// containerLabels reads the labels the runtime holds for a container.
//
// The listing does not carry them in a shape both runtimes agree on, so this
// asks the runtime directly. An error yields no labels rather than a partial
// set: a half-read label map would let an ownership check pass on absence.
func (m *Manager) containerLabels(ctx context.Context, containerID string) map[string]string {
	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, "inspect", containerID,
		"--format", "{{json .Config.Labels}}")
	output, err := cmd.Output()
	if err != nil {
		m.logger.Warn("Failed to read container labels",
			slog.String("container_id", containerID),
			slog.String("error", err.Error()))
		return nil
	}

	labels := make(map[string]string)
	if err := json.Unmarshal(output, &labels); err != nil {
		m.logger.Warn("Failed to parse container labels",
			slog.String("container_id", containerID),
			slog.String("error", err.Error()))
		return nil
	}
	return labels
}

// jsonString reads the first present string field, so one parser handles both
// the Docker and Podman spellings of the same listing.
func jsonString(source map[string]interface{}, keys ...string) string {
	for _, key := range keys {
		if value, ok := source[key].(string); ok && value != "" {
			return value
		}
	}
	return ""
}

func (m *Manager) discoverContainers(ctx context.Context) error {
	// List all containers with our prefix
	// Use {{json .}} to get JSON lines output which is compatible across more versions
	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, "ps", "-a", "--format", "{{json .}}")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("failed to list containers: %w", err)
	}

	if len(output) == 0 {
		return nil
	}

	var podmanContainers []map[string]interface{}

	// Parse NDJSON (newline delimited JSON)
	lines := strings.Split(string(output), "\n")
	for _, line := range lines {
		if strings.TrimSpace(line) == "" {
			continue
		}
		var container map[string]interface{}
		if err := json.Unmarshal([]byte(line), &container); err != nil {
			m.logger.Warn("Failed to parse container line", slog.String("line", line), slog.String("error", err.Error()))
			continue
		}
		podmanContainers = append(podmanContainers, container)
	}

	prefix := m.config.Container.NamePrefix
	for _, pc := range podmanContainers {
		// Docker and Podman disagree on the shape of this field: Podman emits an
		// array, Docker a comma-separated string. Reading only the array meant
		// discovery silently found nothing on Docker — every container failed the
		// type assertion and was skipped. That went unnoticed while the manager
		// always re-synced its instances from the Core API on boot; a data plane
		// has no Core API, so it forgot every instance across a restart and could
		// never wake a stopped one.
		containerName := ""
		switch names := pc["Names"].(type) {
		case string:
			containerName, _, _ = strings.Cut(names, ",")
		case []interface{}:
			if len(names) > 0 {
				containerName, _ = names[0].(string)
			}
		}

		if containerName == "" || !strings.HasPrefix(containerName, prefix) {
			continue
		}

		// The name prefix alone is too broad: the manager's own container is
		// called mcp-manager, and anything a human started by hand can share the
		// prefix too. Adopting those would put the manager under its own
		// lifecycle management. Every instance the manager creates is stamped
		// with MCP_INSTANCE_ID, so that — not the name — is what marks a
		// container as ours.
		environment := m.containerEnvironment(ctx, jsonString(pc, "Id", "ID"))
		if environment["MCP_INSTANCE_ID"] == "" {
			m.logger.Debug("Ignoring container that this manager did not create",
				slog.String("name", containerName))
			continue
		}

		// Same split as Names: Podman spells this "Id", Docker "ID". A bare type
		// assertion on the missing one panics the process during startup.
		containerID := jsonString(pc, "Id", "ID")
		if containerID == "" {
			m.logger.Warn("Skipping container with no id in listing", slog.String("name", containerName))
			continue
		}

		// Extract service name from container environment (original name)
		// First try to get original service name from environment variable
		originalServiceName := ""
		if inspectCmd := exec.CommandContext(ctx, m.config.Container.Runtime, "inspect", containerID, "--format", "{{.Config.Env}}"); inspectCmd != nil {
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

		// Get container port from inspect
		port := 8000 // Default port
		if inspectCmd := exec.CommandContext(ctx, m.config.Container.Runtime, "inspect", containerID, "--format", "{{.Config.Env}}"); inspectCmd != nil {
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

		// Generate slug from service name
		slug := generateSlug(serviceName)

		container := &models.Container{
			ID:          containerID,
			Name:        containerName,
			ServiceName: serviceName,
			Slug:        slug,
			Image:       jsonString(pc, "Image"),
			Status:      m.mapPodmanStatus(jsonString(pc, "State", "Status")),
			Port:        port,
			URL:         fmt.Sprintf("/mcp/%s", slug),
			Host:        containerName,
			// Labels are read back rather than left empty because they carry
			// ownership. A data plane decides whether an instance is its own by
			// the label on it, so a rediscovered container without labels is
			// indistinguishable from someone else's and can never be served
			// again after a restart.
			Labels: m.containerLabels(ctx, containerID),
			// Carries MCP_INSTANCE_ID, which is how a caller's instance id is
			// resolved back to a service name. Left empty, every lookup by
			// instance id misses and the container is unreachable after a
			// restart even though it is sitting right there.
			Environment: environment,
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

// runtimeRefusal classifies why a runtime would not create a container.
//
// The reason has to cross the API, because until it did the control plane showed
// a bare exit status and the cause was visible only to whoever could read the
// host journal. The runtime\x27s own text does not cross: it can carry host paths
// and registry hints, and the caller can act on the class alone. The full output
// stays in the error log next to this call.
func runtimeRefusal(output []byte) string {
	lowered := strings.ToLower(string(output))
	switch {
	case strings.Contains(lowered, "pull access denied"),
		strings.Contains(lowered, "requested access to the resource is denied"),
		strings.Contains(lowered, "authentication required"),
		strings.Contains(lowered, "unauthorized"):
		return "the image registry refused the pull; this host has no credentials for it"
	case strings.Contains(lowered, "manifest unknown"),
		strings.Contains(lowered, "not found"),
		strings.Contains(lowered, "repository does not exist"):
		return "the image does not exist in the registry"
	case strings.Contains(lowered, "already in use by container"):
		return "a container already holds this instance\x27s name"
	case strings.Contains(lowered, "no space left on device"):
		return "the host is out of disk"
	case strings.Contains(lowered, "no such image"):
		return "the image is not present on this host"
	case len(strings.TrimSpace(lowered)) == 0:
		return "the runtime failed without output"
	default:
		return "the runtime rejected the container; see the data-plane log for its output"
	}
}

// containerOutput reads the tail of what a container printed. A start failure
// reaches the caller as "the process is gone"; the reason is in the process's own
// output, so it belongs in the data-plane log -- otherwise the only way to learn
// that a server refused its arguments is to reproduce it by hand on the host.
func (m *Manager) containerOutput(ctx context.Context, id string) string {
	output, err := exec.CommandContext(ctx, m.config.Container.Runtime, "logs", "--tail", "20", id).CombinedOutput()
	trimmed := strings.TrimSpace(string(output))
	if err != nil && trimmed == "" {
		return "no output could be read: " + err.Error()
	}
	return trimmed
}

// firstNonEmpty returns the first value that was actually set.
func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

// containerAlreadyGone reports whether a runtime refused an operation because
// the container does not exist. Runtimes disagree on the exit code for that, so
// the message is what can be relied on.
func containerAlreadyGone(output []byte) bool {
	return strings.Contains(strings.ToLower(string(output)), "no such container")
}

// clearContainerName frees the runtime name a workload is about to take.
//
// A container name is derived from the instance it serves, so a leftover
// container under that name is the same instance's corpse from an earlier
// attempt: it can never serve traffic again, yet the runtime refuses to reuse
// its name. That turned every retry for the instance into a permanent "name is
// already in use" failure which hid the original start error and left the
// instance id unusable for good. A *running* namesake is a different situation
// -- something is actively serving under it -- so it is reported, not killed.
func (m *Manager) clearContainerName(ctx context.Context, name string) error {
	state, err := exec.CommandContext(ctx, m.config.Container.Runtime, "inspect", name, "--format", "{{.State.Running}}").Output()
	if err != nil {
		// Nothing answers to that name. This is the ordinary case.
		return nil
	}

	if strings.TrimSpace(string(state)) == "true" {
		return fmt.Errorf("container %s is already running", name)
	}

	if output, err := exec.CommandContext(ctx, m.config.Container.Runtime, "rm", "-f", name).CombinedOutput(); err != nil {
		return fmt.Errorf("removing stale container %s: %w: %s", name, err, strings.TrimSpace(string(output)))
	}

	m.logger.Info("Removed a stale container holding the name of a new workload",
		slog.String("container", name))

	return nil
}

// buildContainerRunArgs builds the arguments for the container runtime run command.
// MCP containers intentionally have no external router labels: every request
// must cross the manager demand gateway so lifecycle leases stay authoritative.
func (m *Manager) buildContainerRunArgs(container *models.Container) []string {
	args := []string{"run", "-d"}

	// Add name
	args = append(args, "--name", container.Name)

	// Add network for container-to-container communication
	args = append(args, "--network", m.config.Container.Network)

	// Add environment variables
	for key, value := range container.Environment {
		args = append(args, "-e", fmt.Sprintf("%s=%s", key, value))
	}

	// Add user-supplied labels
	for key, value := range container.Labels {
		args = append(args, "--label", fmt.Sprintf("%s=%s", key, value))
	}

	// Add isolation flags. MCP servers are third-party code; without these the
	// container runs with the daemon's full default capability set next to the
	// control plane.
	args = append(args, isolationRunArgs(container.Isolation)...)

	// What this workload may take. The request wins over the host default: the
	// ceiling belongs to the workload, and a caller that sizes one instance
	// differently -- a paid tier, a heavy server -- had its value accepted and
	// then dropped here, so every container ran on the one host-wide number.
	if memory := firstNonEmpty(container.MemoryLimit, m.config.Container.DefaultMemoryLimit); memory != "" {
		args = append(args, "--memory", memory)
	}

	if cpus := firstNonEmpty(container.CPULimit, m.config.Container.DefaultCPULimit); cpus != "" {
		args = append(args, "--cpus", cpus)
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
			cmd := exec.CommandContext(ctx, m.config.Container.Runtime, "inspect", containerID, "--format", "{{.State.Status}}")
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

	// Resolve the actual container spec (handles both "docker" and "command" types)
	image, containerPort, command, environment := ResolveContainerSpec(jsonSpec)
	if image == "" {
		return fmt.Errorf("image is required in json_spec (or use type='command')")
	}
	isolation, err := config.ResolveIsolation(m.config.Container.DefaultIsolationTier)
	if err != nil {
		return fmt.Errorf("resolve MCP isolation policy: %w", err)
	}

	// Get container name for later use
	containerName := m.config.GetContainerName(name)

	// Add MCP-specific environment variables
	environment["MCP_INSTANCE_ID"] = instanceID
	environment["MCP_SERVICE_NAME"] = name
	environment["MCP_CONTAINER_PORT"] = fmt.Sprintf("%d", containerPort)

	// NOW ACQUIRE MUTEX FOR CONTAINER OPERATIONS
	m.mutex.Lock()
	defer m.mutex.Unlock()

	// Check if container already exists
	if existing, exists := m.containers[name]; exists {
		if existing.Status == models.StatusRunning || existing.Status == models.StatusHealthy || existing.Status == models.StatusStarting {
			return nil
		}
		return fmt.Errorf("container %s already exists in state %s", name, existing.Status)
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
		URL:         fmt.Sprintf("/mcp/%s", slug),
		Host:        containerName,
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
		Labels:      make(map[string]string),
		Environment: environment,
		Command:     command,
		Isolation:   isolation,
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

	// The name has to be free before the run, or the retry that follows a failed
	// start reports a name conflict instead of the reason the start failed.
	if err := m.clearContainerName(ctx, containerName); err != nil {
		container.Status = models.StatusError
		return err
	}

	// Build container run command
	args := m.buildContainerRunArgs(container)

	// Execute container runtime run command
	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		container.Status = models.StatusError

		// Publish failed status
		errorMsg := fmt.Sprintf("Failed to create container: %s", runtimeRefusal(output))
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

	// Update final status — Traefik discovers the container via labels
	container.Status = models.StatusRunning
	container.UpdatedAt = time.Now()

	// Publish running status
	if err := m.eventPublisher.PublishRunning(ctx, instanceID, name, container.ID, container.URL); err != nil {
		m.logger.Warn("Failed to publish running status",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	}

	m.logger.Info("Container created successfully",
		slog.String("container", containerName),
		slog.String("id", container.ID),
		slog.String("instance_id", instanceID),
		slog.String("url", container.URL),
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

	// Delete the container using existing functionality (includes route cleanup)
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

// sandboxImage is the container image used to wrap stdio-based MCP servers over streamable-http.
// agentarea/mcp-bridge includes Python, Node.js (npx), and uv (uvx) so most MCP servers work
// out of the box. It proxies stdio-based MCP servers over streamable-http at /mcp.
const sandboxImage = "agentarea/mcp-bridge:latest"
const sandboxPort = 8080

// ResolveContainerSpec derives the actual image, port, command, and environment that
// should be used when launching a container for a given json_spec.
//
// Two spec types are supported:
//   - "docker" (default): the spec must contain "image" and "port". The container is
//     launched as-is and is expected to serve MCP over HTTP/SSE natively.
//   - "command": the spec must contain "command" (e.g. "npx" or "uvx") plus optional
//     "args". The command is wrapped with mcp-bridge so its stdio transport is
//     exposed over HTTP/SSE on sandboxPort.
func ResolveContainerSpec(jsonSpec map[string]interface{}) (image string, port int, command []string, environment map[string]string) {
	environment = make(map[string]string)
	if envMap, ok := jsonSpec["environment"].(map[string]interface{}); ok {
		for k, v := range envMap {
			if s, ok := v.(string); ok {
				environment[k] = s
			}
		}
	}

	specType, _ := jsonSpec["type"].(string)

	if specType == "command" {
		// Wrap stdio command with mcp-bridge (stdio → streamable-http proxy)
		cmd, _ := jsonSpec["command"].(string)
		var args []string
		if rawArgs, ok := jsonSpec["args"].([]interface{}); ok {
			for _, a := range rawArgs {
				if s, ok := a.(string); ok {
					args = append(args, s)
				}
			}
		}

		image = sandboxImage
		port = sandboxPort
		// bridge.py <command> [args...] — the entrypoint is "python bridge.py"
		command = append([]string{cmd}, args...)
		return
	}

	// Docker type (default)
	image, _ = jsonSpec["image"].(string)
	if p, ok := jsonSpec["port"].(float64); ok {
		port = int(p)
	} else if p, ok := jsonSpec["port"].(int); ok {
		port = p
	} else {
		port = 8000
	}

	// Optional command override (supports both "cmd" and "command" keys)
	cmdInterface, ok := jsonSpec["cmd"]
	if !ok {
		cmdInterface, ok = jsonSpec["command"]
	}
	if ok {
		if cmdSlice, ok := cmdInterface.([]interface{}); ok {
			for _, cmdItem := range cmdSlice {
				if cmdStr, ok := cmdItem.(string); ok {
					command = append(command, cmdStr)
				}
			}
		}
	}
	return
}

// generateSlug generates a URL-friendly slug from a name
func generateSlug(name string) string {
	// Convert to lowercase and replace spaces/special chars with hyphens
	slug := strings.ToLower(name)

	// Replace any non-alphanumeric characters with hyphens
	reg := regexp.MustCompile(`[^a-z0-9]+`)
	slug = reg.ReplaceAllString(slug, "-")

	// Remove leading/trailing hyphens
	slug = strings.Trim(slug, "-")

	return slug
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

	// Additional image validation/pull if requested (skip for command type)
	specType, _ := instance.JSONSpec["type"].(string)
	if allowImagePull && specType != "command" {
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

	// Additional image validation/pull if requested (skip for command type)
	specType, _ := instance.JSONSpec["type"].(string)
	if allowImagePull && specType != "command" {
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

// getRealTimeContainerStatus gets the real-time status from the container runtime
func (m *Manager) getRealTimeContainerStatus(ctx context.Context, container *models.Container) models.ContainerStatus {
	if container.ID == "" {
		return models.StatusError
	}

	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, "inspect", container.ID, "--format", "{{.State.Status}}")
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
	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, "start", container.ID)
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

	// Update final status — Traefik re-discovers the container automatically
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

// syncWithCoreAPI synchronizes with the database to handle instances that need containers.
// Queries the DB directly to avoid HTTP auth complexity.
func (m *Manager) syncWithCoreAPI(ctx context.Context) error {
	m.logger.Info("Starting database synchronization for pending instances")

	connStr := database.BuildConnStr(m.logger)
	if connStr == "" {
		m.logger.Warn("Database credentials not configured, skipping instance sync")
		return nil
	}

	db, err := sql.Open("pgx", connStr)
	if err != nil {
		return fmt.Errorf("failed to open database connection: %w", err)
	}
	defer db.Close()

	if err := db.PingContext(ctx); err != nil {
		return fmt.Errorf("failed to connect to database: %w", err)
	}

	// Fetch all instances that should have a running container
	// Includes 'pending', 'starting', and 'running' because start_instance
	// may update DB status without actually creating the container
	rows, err := db.QueryContext(ctx,
		`SELECT id::text, name, json_spec FROM mcp_server_instances WHERE status IN ('pending', 'starting', 'running')`)
	if err != nil {
		return fmt.Errorf("failed to query mcp_server_instances: %w", err)
	}
	defer rows.Close()

	var instances []models.MCPServerInstance
	for rows.Next() {
		var inst models.MCPServerInstance
		var jsonSpecRaw []byte
		if err := rows.Scan(&inst.InstanceID, &inst.Name, &jsonSpecRaw); err != nil {
			m.logger.Warn("Failed to scan instance row", slog.String("error", err.Error()))
			continue
		}
		if err := json.Unmarshal(jsonSpecRaw, &inst.JSONSpec); err != nil {
			m.logger.Warn("Failed to parse json_spec",
				slog.String("instance_id", inst.InstanceID),
				slog.String("error", err.Error()))
			continue
		}
		instances = append(instances, inst)
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("error iterating instance rows: %w", err)
	}

	m.logger.Info("Fetched instances from database", slog.Int("total", len(instances)))

	pendingCount := 0
	for _, instance := range instances {
		m.logger.Info("Processing instance",
			slog.String("instance_id", instance.InstanceID),
			slog.String("name", instance.Name))

		// Skip if container already tracked in memory
		if _, exists := m.containers[instance.Name]; exists {
			m.logger.Debug("Container already exists, skipping", slog.String("name", instance.Name))
			continue
		}

		image, port, command, environment := ResolveContainerSpec(instance.JSONSpec)
		if image == "" {
			m.logger.Error("Invalid json_spec for instance (missing image or command)",
				slog.String("instance_id", instance.InstanceID))
			continue
		}

		// Resolve secret env vars from encrypted_secrets table (shared with the
		// HTTP create path via Manager.ResolveSecretEnvVars).
		for k, v := range m.ResolveSecretEnvVars(instance.InstanceID, instance.JSONSpec) {
			environment[k] = v
		}

		environment["MCP_INSTANCE_ID"] = instance.InstanceID

		req := models.CreateContainerRequest{
			ServiceName: instance.Name,
			Image:       image,
			Port:        port,
			Environment: environment,
			Command:     command,
		}

		if _, err := m.CreateContainer(ctx, req); err != nil {
			m.logger.Error("Failed to create container for instance",
				slog.String("instance_id", instance.InstanceID),
				slog.String("name", instance.Name),
				slog.String("error", err.Error()))
		} else {
			m.logger.Info("Successfully created container for instance",
				slog.String("instance_id", instance.InstanceID),
				slog.String("name", instance.Name))
			pendingCount++
		}
	}

	m.logger.Info("Database synchronization completed",
		slog.Int("total_instances", len(instances)),
		slog.Int("containers_created", pendingCount))

	return nil
}
