package providers

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/secrets"
)

// DockerProvider handles Docker-based MCP server instances
type DockerProvider struct {
	secretResolver   secrets.SecretResolver
	containerManager ContainerManagerInterface
	logger           *slog.Logger
}

// ContainerManagerInterface defines the interface for container management
type ContainerManagerInterface interface {
	HandleMCPInstanceCreated(ctx context.Context, instanceID, name string, jsonSpec map[string]interface{}) error
	HandleMCPInstanceDeleted(ctx context.Context, instanceID string) error
}

// NewDockerProvider creates a new Docker provider
func NewDockerProvider(secretResolver secrets.SecretResolver, containerManager ContainerManagerInterface, logger *slog.Logger) *DockerProvider {
	return &DockerProvider{
		secretResolver:   secretResolver,
		containerManager: containerManager,
		logger:           logger,
	}
}

// CreateInstance creates a new Docker container for the MCP server using the container manager
func (p *DockerProvider) CreateInstance(ctx context.Context, instance *models.MCPServerInstance) error {
	p.logger.Info("Creating Docker container via container manager",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name))

	// Resolve secrets in the json_spec before passing to container manager
	resolvedSpec := make(map[string]interface{})
	for key, value := range instance.JSONSpec {
		resolvedSpec[key] = value
	}

	// Resolve environment variables (including secrets)
	if envInterface, exists := resolvedSpec["environment"]; exists {
		if envMap, ok := envInterface.(map[string]interface{}); ok {
			// Convert map[string]interface{} to map[string]string
			stringEnvMap := make(map[string]string)
			for key, value := range envMap {
				stringEnvMap[key] = fmt.Sprintf("%v", value)
			}

			resolvedEnv, err := p.secretResolver.ResolveSecrets(instance.InstanceID, stringEnvMap)
			if err != nil {
				p.logger.Error("Failed to resolve secrets",
					slog.String("instance_id", instance.InstanceID),
					slog.String("error", err.Error()))
				return fmt.Errorf("failed to resolve secrets: %w", err)
			}

			// Convert back to map[string]interface{} for json_spec
			resolvedEnvInterface := make(map[string]interface{})
			for key, value := range resolvedEnv {
				resolvedEnvInterface[key] = value
			}
			resolvedSpec["environment"] = resolvedEnvInterface
		}
	}

	// Use the container manager to create the container
	// This ensures the container is properly tracked in the manager's internal map
	err := p.containerManager.HandleMCPInstanceCreated(ctx, instance.InstanceID, instance.Name, resolvedSpec)
	if err != nil {
		p.logger.Error("Failed to create container via container manager",
			slog.String("instance_id", instance.InstanceID),
			slog.String("error", err.Error()))
		return fmt.Errorf("failed to create container: %w", err)
	}

	p.logger.Info("Successfully created Docker container via container manager",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name))

	return nil
}

// DeleteInstance removes the Docker container using the container manager
func (p *DockerProvider) DeleteInstance(ctx context.Context, instanceID, name string) error {
	p.logger.Info("Deleting Docker container via container manager",
		slog.String("instance_id", instanceID),
		slog.String("name", name))

	// Use the container manager to delete the container
	// This ensures the container is properly removed from the manager's tracking
	err := p.containerManager.HandleMCPInstanceDeleted(ctx, instanceID)
	if err != nil {
		p.logger.Error("Failed to delete container via container manager",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
		return fmt.Errorf("failed to delete container: %w", err)
	}

	p.logger.Info("Successfully deleted Docker container via container manager",
		slog.String("instance_id", instanceID),
		slog.String("name", name))

	return nil
}

// GetInstanceStatus returns the status of the Docker container
func (p *DockerProvider) GetInstanceStatus(ctx context.Context, name string) (string, error) {
	// This method can remain as-is since it's just querying status
	// In a more complete implementation, this could also use the container manager
	p.logger.Info("Getting instance status",
		slog.String("name", name))

	// For now, return a placeholder status
	// In a real implementation, this would query the container manager
	return "running", nil
}
