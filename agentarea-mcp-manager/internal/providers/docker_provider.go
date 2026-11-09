package providers

import (
	"context"
	"fmt"
	"log/slog"
	"maps"

	"github.com/agentarea/mcp-manager/internal/mcpcontext"
	"github.com/agentarea/mcp-manager/internal/mcpstorage"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/secrets"
)

// DockerProvider handles Docker-based MCP server instances
type DockerProvider struct {
	secretResolver   secrets.SecretResolver
	containerManager ContainerManagerInterface
	storage          *mcpstorage.Issuer
	context          *mcpcontext.Issuer
	logger           *slog.Logger
	hook             InstanceSpecHook
}

// ContainerManagerInterface defines the interface for container management
type ContainerManagerInterface interface {
	HandleMCPInstanceCreated(ctx context.Context, instanceID, name, workspaceID string, jsonSpec map[string]interface{}) error
	HandleMCPInstanceDeleted(ctx context.Context, instanceID string) error
}

// NewDockerProvider creates a new Docker provider
func NewDockerProvider(secretResolver secrets.SecretResolver, containerManager ContainerManagerInterface, storage *mcpstorage.Issuer, logger *slog.Logger) *DockerProvider {
	return &DockerProvider{
		secretResolver:   secretResolver,
		containerManager: containerManager,
		storage:          storage,
		logger:           logger,
	}
}

// SetContextIssuer installs the issuer of opted-in instances' caller-context key.
func (p *DockerProvider) SetContextIssuer(issuer *mcpcontext.Issuer) {
	p.context = issuer
}

// SetInstanceSpecHook installs the hook called on every assembled spec before
// its container is created.
func (p *DockerProvider) SetInstanceSpecHook(hook InstanceSpecHook) {
	p.hook = hook
}

// CreateInstance creates a new Docker container for the MCP server using the container manager
func (p *DockerProvider) CreateInstance(ctx context.Context, instance *models.MCPServerInstance) error {
	p.logger.Info("Creating Docker container via container manager",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name))

	if err := refuseStdioImage(instance.JSONSpec); err != nil {
		return err
	}
	resolvedSpec, err := resolveInstanceSpecSecrets(p.secretResolver, instance.InstanceID, instance.JSONSpec)
	if err != nil {
		p.logger.Error("Failed to resolve MCP instance environment",
			slog.String("instance_id", instance.InstanceID),
			slog.String("error", err.Error()))
		return err
	}
	storageEnvironment, err := p.storage.Environment(instance)
	if err != nil {
		p.logger.Error("Failed to issue MCP storage environment",
			slog.String("instance_id", instance.InstanceID),
			slog.String("error", err.Error()))
		return err
	}
	resolvedSpec = withEnvironment(resolvedSpec, storageEnvironment)
	contextEnvironment, err := p.context.Environment(instance)
	if err != nil {
		p.logger.Error("Failed to issue MCP caller-context key",
			slog.String("instance_id", instance.InstanceID),
			slog.String("error", err.Error()))
		return err
	}
	resolvedSpec = withEnvironment(resolvedSpec, contextEnvironment)
	if resolvedSpec, err = p.applyInstanceSpecHook(ctx, instance, resolvedSpec); err != nil {
		return err
	}

	// Use the container manager to create the container
	// This ensures the container is properly tracked in the manager's internal map
	err = p.containerManager.HandleMCPInstanceCreated(ctx, instance.InstanceID, instance.InstanceID, instance.WorkspaceID, resolvedSpec)
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

// applyInstanceSpecHook shows the hook the container's environment as a backend
// spec and returns jsonSpec carrying the environment the hook left.
func (p *DockerProvider) applyInstanceSpecHook(ctx context.Context, instance *models.MCPServerInstance, jsonSpec map[string]any) (map[string]any, error) {
	if p.hook == nil {
		return jsonSpec, nil
	}
	assembled := *instance
	assembled.JSONSpec = jsonSpec
	spec := (&BackendProvider{}).convertToInstanceSpec(&assembled)
	if err := p.hook(ctx, instance, spec); err != nil {
		p.logger.Error("Instance spec hook refused the instance",
			slog.String("instance_id", instance.InstanceID),
			slog.String("error", err.Error()))
		return nil, fmt.Errorf("instance spec hook: %w", err)
	}
	environment := make(map[string]any, len(spec.Environment))
	for key, value := range spec.Environment {
		environment[key] = value
	}
	out := maps.Clone(jsonSpec)
	out["environment"] = environment
	return out, nil
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
