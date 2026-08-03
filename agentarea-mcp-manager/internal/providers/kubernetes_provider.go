package providers

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/secrets"
)

// sandboxImage / sandboxPort mirror the constants in internal/container.
// Duplicated to avoid an import cycle (container → models → providers).
const (
	sandboxImage = "agentarea/mcp-bridge:latest"
	sandboxPort  = 8080
)

// BackendInstanceSpec defines the specification for creating an instance
// (local copy to avoid import cycle).
type BackendInstanceSpec struct {
	InstanceID  string
	Name        string
	ServiceName string
	Image       string
	Port        int
	Environment map[string]string
	Labels      map[string]string
	// Command maps to CMD / K8s container.args — arguments appended to
	// the image's existing ENTRYPOINT.
	Command       []string
	IsolationTier string
	Resources     struct {
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
	secrets secrets.SecretResolver
}

// NewKubernetesProvider creates a new Kubernetes provider
func NewKubernetesProvider(backend Backend, secretResolver secrets.SecretResolver, logger *slog.Logger) *KubernetesProvider {
	return &KubernetesProvider{
		backend: backend,
		logger:  logger,
		secrets: secretResolver,
	}
}

// CreateInstance creates a new Kubernetes deployment/service for the MCP server
func (p *KubernetesProvider) CreateInstance(ctx context.Context, instance *models.MCPServerInstance) error {
	p.logger.Info("Creating Kubernetes instance via backend",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name))

	resolvedJSON, err := resolveInstanceSpecSecrets(p.secrets, instance.InstanceID, instance.JSONSpec)
	if err != nil {
		return err
	}
	resolvedInstance := *instance
	resolvedInstance.JSONSpec = resolvedJSON
	// Convert MCPServerInstance to backend InstanceSpec
	spec := p.convertToInstanceSpec(&resolvedInstance)

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
		return fmt.Errorf("failed to delete Kubernetes instance: %w", err)
	}

	p.logger.Info("Successfully deleted Kubernetes instance via backend",
		slog.String("instance_id", instanceID),
		slog.String("name", name))

	return nil
}

// convertToInstanceSpec converts an MCPServerInstance to a backend InstanceSpec.
//
// For command-type instances we wrap the stdio command in mcp-bridge (same as
// the docker-mode handler does). Otherwise deployment would be created with
// empty image + port=0 and rejected by the K8s apiserver.
func (p *KubernetesProvider) convertToInstanceSpec(instance *models.MCPServerInstance) *BackendInstanceSpec {
	spec := &BackendInstanceSpec{
		InstanceID:    instance.InstanceID,
		Name:          instance.InstanceID,
		ServiceName:   instance.InstanceID,
		IsolationTier: config.IsolationUntrusted,
	}

	jsonSpec := instance.JSONSpec
	specType, _ := jsonSpec["type"].(string)

	if specType == "command" {
		// command-type: always wraps stdio command with mcp-bridge.
		cmd, _ := jsonSpec["command"].(string)
		var args []string
		if rawArgs, ok := jsonSpec["args"].([]any); ok {
			for _, a := range rawArgs {
				if s, ok := a.(string); ok {
					args = append(args, s)
				}
			}
		}
		spec.Image = sandboxImage
		spec.Port = sandboxPort
		// mcp-bridge's ENTRYPOINT is `python bridge.py`. The stdio command
		// + args are appended as CLI arguments (K8s container.args).
		spec.Command = append([]string{cmd}, args...)
	} else {
		// docker-type: use the image directly — it must serve HTTP natively.
		// Strip --transport=stdio: in K8s the container must bind a port
		// directly (no traefik gateway), and stdio-capable images default to
		// HTTP SSE when this flag is absent.
		if image, ok := jsonSpec["image"].(string); ok {
			spec.Image = image
		}
		if port, ok := jsonSpec["port"].(float64); ok {
			spec.Port = int(port)
		} else if port, ok := jsonSpec["port"].(int); ok {
			spec.Port = port
		}
		if rawCmd, ok := jsonSpec["command"].([]any); ok {
			for _, a := range rawCmd {
				if s, ok := a.(string); ok && s != "--transport=stdio" {
					spec.Command = append(spec.Command, s)
				}
			}
		}
	}

	// Extract environment variables
	if envInterface, exists := instance.JSONSpec["environment"]; exists {
		if envMap, ok := envInterface.(map[string]any); ok {
			env := make(map[string]string)
			for key, value := range envMap {
				env[key] = fmt.Sprintf("%v", value)
			}
			spec.Environment = env
		}
	}

	// Also check for env_vars (alternative key)
	if envInterface, exists := instance.JSONSpec["env_vars"]; exists {
		if envMap, ok := envInterface.(map[string]any); ok {
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
		if labelsMap, ok := labelsInterface.(map[string]any); ok {
			labels := make(map[string]string)
			for key, value := range labelsMap {
				labels[key] = fmt.Sprintf("%v", value)
			}
			spec.Labels = labels
		}
	}

	// Extract resource limits
	if resourcesInterface, exists := instance.JSONSpec["resource_limits"]; exists {
		if resourcesMap, ok := resourcesInterface.(map[string]any); ok {
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
