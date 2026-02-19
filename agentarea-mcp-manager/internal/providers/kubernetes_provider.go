package providers

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/agentarea/mcp-manager/internal/models"
)

// BackendInstanceSpec defines the specification for creating an instance
// (local copy to avoid import cycle)
type BackendInstanceSpec struct {
	InstanceID  string
	Name        string
	ServiceName string
	Image       string
	Port        int
	Environment map[string]string
	Labels      map[string]string
	Command     []string
	Resources   struct {
		Limits   struct{ CPU, Memory string }
		Requests struct{ CPU, Memory string }
	}
}

// BackendInstanceResult represents the result of creating an instance
type BackendInstanceResult struct {
	ID     string
	Name   string
	URL    string
	Status string
}

// Backend defines the interface that Kubernetes backend must satisfy
type Backend interface {
	CreateInstance(ctx context.Context, spec *BackendInstanceSpec) (*BackendInstanceResult, error)
	DeleteInstance(ctx context.Context, instanceID string) error
}

// KubernetesProvider handles Kubernetes-based MCP server instances
type KubernetesProvider struct {
	backend Backend
	logger  *slog.Logger
}

// NewKubernetesProvider creates a new Kubernetes provider
func NewKubernetesProvider(backend Backend, logger *slog.Logger) *KubernetesProvider {
	return &KubernetesProvider{
		backend: backend,
		logger:  logger,
	}
}

// CreateInstance creates a new Kubernetes deployment/service for the MCP server
func (p *KubernetesProvider) CreateInstance(ctx context.Context, instance *models.MCPServerInstance) error {
	p.logger.Info("Creating Kubernetes instance via backend",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name))

	// Convert MCPServerInstance to backend InstanceSpec
	spec := p.convertToInstanceSpec(instance)

	// Use the backend to create the instance
	result, err := p.backend.CreateInstance(ctx, spec)
	if err != nil {
		p.logger.Error("Failed to create Kubernetes instance via backend",
			slog.String("instance_id", instance.InstanceID),
			slog.String("error", err.Error()))
		return fmt.Errorf("failed to create Kubernetes instance: %w", err)
	}

	p.logger.Info("Successfully created Kubernetes instance via backend",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name),
		slog.String("url", result.URL))

	return nil
}

// DeleteInstance removes the Kubernetes resources for an MCP server
func (p *KubernetesProvider) DeleteInstance(ctx context.Context, instanceID, name string) error {
	p.logger.Info("Deleting Kubernetes instance via backend",
		slog.String("instance_id", instanceID),
		slog.String("name", name))

	// Use the backend to delete the instance
	if err := p.backend.DeleteInstance(ctx, instanceID); err != nil {
		p.logger.Error("Failed to delete Kubernetes instance via backend",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
		// Don't return error - instance might not exist
		return nil
	}

	p.logger.Info("Successfully deleted Kubernetes instance via backend",
		slog.String("instance_id", instanceID),
		slog.String("name", name))

	return nil
}

// convertToInstanceSpec converts an MCPServerInstance to a backend InstanceSpec
func (p *KubernetesProvider) convertToInstanceSpec(instance *models.MCPServerInstance) *BackendInstanceSpec {
	spec := &BackendInstanceSpec{
		InstanceID:  instance.InstanceID,
		Name:        instance.Name,
		ServiceName: instance.Name,
	}

	// Extract image from json_spec
	if image, ok := instance.JSONSpec["image"].(string); ok {
		spec.Image = image
	}

	// Extract port from json_spec
	if port, ok := instance.JSONSpec["port"].(float64); ok {
		spec.Port = int(port)
	} else if port, ok := instance.JSONSpec["port"].(int); ok {
		spec.Port = port
	}

	// Extract environment variables
	if envInterface, exists := instance.JSONSpec["environment"]; exists {
		if envMap, ok := envInterface.(map[string]interface{}); ok {
			env := make(map[string]string)
			for key, value := range envMap {
				env[key] = fmt.Sprintf("%v", value)
			}
			spec.Environment = env
		}
	}

	// Also check for env_vars (alternative key)
	if envInterface, exists := instance.JSONSpec["env_vars"]; exists {
		if envMap, ok := envInterface.(map[string]interface{}); ok {
			if spec.Environment == nil {
				spec.Environment = make(map[string]string)
			}
			for key, value := range envMap {
				spec.Environment[key] = fmt.Sprintf("%v", value)
			}
		}
	}

	// Extract labels
	if labelsInterface, exists := instance.JSONSpec["labels"]; exists {
		if labelsMap, ok := labelsInterface.(map[string]interface{}); ok {
			labels := make(map[string]string)
			for key, value := range labelsMap {
				labels[key] = fmt.Sprintf("%v", value)
			}
			spec.Labels = labels
		}
	}

	// Extract resource limits
	if resourcesInterface, exists := instance.JSONSpec["resource_limits"]; exists {
		if resourcesMap, ok := resourcesInterface.(map[string]interface{}); ok {
			if memory, ok := resourcesMap["memory"].(string); ok {
				spec.Resources.Limits.Memory = memory
			}
			if cpu, ok := resourcesMap["cpu"].(string); ok {
				spec.Resources.Limits.CPU = cpu
			} else if cpu, ok := resourcesMap["cpu"].(float64); ok {
				spec.Resources.Limits.CPU = fmt.Sprintf("%f", cpu)
			}
		}
	}

	return spec
}
