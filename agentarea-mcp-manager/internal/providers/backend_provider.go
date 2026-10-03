package providers

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/agentarea/mcp-manager/internal/mcpbase"
	"github.com/agentarea/mcp-manager/internal/mcpspec"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/secrets"
)

// BackendInstanceSpec defines the specification for creating an instance
// (local copy to avoid import cycle).
type BackendInstanceSpec struct {
	InstanceID  string
	WorkspaceID string
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

// BackendProvider drives MCP workloads through a Backend: an in-cluster
// Kubernetes API, or a remote data plane reached over HTTP.
type BackendProvider struct {
	backend Backend
	logger  *slog.Logger
	secrets secrets.SecretResolver
}

// NewBackendProvider creates a provider over any Backend
func NewBackendProvider(backend Backend, secretResolver secrets.SecretResolver, logger *slog.Logger) *BackendProvider {
	return &BackendProvider{
		backend: backend,
		logger:  logger,
		secrets: secretResolver,
	}
}

// CreateInstance creates a new Kubernetes deployment/service for the MCP server
func (p *BackendProvider) CreateInstance(ctx context.Context, instance *models.MCPServerInstance) error {
	p.logger.Info("Creating Kubernetes instance via backend",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name))
	spec, err := BuildBackendInstanceSpec(instance, p.secrets)
	if err != nil {
		return err
	}

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
func (p *BackendProvider) DeleteInstance(ctx context.Context, instanceID, name string) error {
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

// BuildBackendInstanceSpec resolves an instance's environment and converts its
// JSON specification to the backend shape used by container providers.
func BuildBackendInstanceSpec(instance *models.MCPServerInstance, resolver secrets.SecretResolver) (*BackendInstanceSpec, error) {
	if instance == nil {
		return nil, fmt.Errorf("MCP instance is required")
	}
	resolvedJSON, err := resolveInstanceSpecSecrets(resolver, instance.InstanceID, instance.JSONSpec)
	if err != nil {
		return nil, err
	}
	resolvedInstance := *instance
	resolvedInstance.JSONSpec = resolvedJSON
	return (&BackendProvider{}).convertToInstanceSpec(&resolvedInstance), nil
}

// convertToInstanceSpec converts an MCPServerInstance to a backend InstanceSpec.
//
// For command-type instances we run the stdio command on the mcp-base image
// (same as the docker-mode handler does). Otherwise deployment would be
// created with empty image + port=0 and rejected by the K8s apiserver.
func (p *BackendProvider) convertToInstanceSpec(instance *models.MCPServerInstance) *BackendInstanceSpec {
	// The tier is deliberately left empty: the backend then applies the
	// operator's AGENTAREA_MCP_ISOLATION. Pinning "untrusted" here asked every MCP
	// pod for a syscall-interposing RuntimeClass, so on a cluster without one the
	// pod stayed Pending until the gateway's startup timeout and the instance was
	// unreachable forever.
	spec := &BackendInstanceSpec{
		InstanceID:  instance.InstanceID,
		WorkspaceID: instance.WorkspaceID,
		Name:        instance.InstanceID,
		ServiceName: instance.InstanceID,
	}
	jsonSpec := instance.JSONSpec
	applyTransportSpec(spec, jsonSpec)
	applyResourceLimits(spec, jsonSpec)
	applyEnvironment(spec, jsonSpec)
	applyLabels(spec, jsonSpec)
	return spec
}

func applyTransportSpec(spec *BackendInstanceSpec, jsonSpec map[string]any) {
	specType, _ := jsonSpec["type"].(string)
	if specType == "command" {
		// command-type: the stdio command runs behind mcp-base's bridge.
		cmd, _ := jsonSpec["command"].(string)
		spec.Image = mcpbase.Image()
		spec.Port = mcpbase.Port
		// mcp-base's ENTRYPOINT is its bridge; the stdio command + args are
		// its arguments (K8s container.args).
		spec.Command = append([]string{cmd}, mcpspec.StringList(jsonSpec["args"])...)
		return
	}
	// docker-type: use the image directly — it must serve HTTP natively.
	if image, ok := jsonSpec["image"].(string); ok {
		spec.Image = image
	}
	if port, ok := jsonSpec["port"].(float64); ok {
		spec.Port = int(port)
	} else if port, ok := jsonSpec["port"].(int); ok {
		spec.Port = port
	}
	spec.Command = mcpspec.DockerArgv(jsonSpec)
}

func applyResourceLimits(spec *BackendInstanceSpec, jsonSpec map[string]any) {
	if resources, ok := jsonSpec["resources"].(map[string]any); ok {
		if limits, ok := resources["limits"].(map[string]any); ok {
			if memory, ok := limits["memory"].(string); ok {
				spec.Resources.Limits.Memory = memory
			}
			if cpu, ok := limits["cpu"].(string); ok {
				spec.Resources.Limits.CPU = cpu
			}
		}
	}
	if resources, ok := jsonSpec["resource_limits"].(map[string]any); ok {
		if memory, ok := resources["memory"].(string); ok {
			spec.Resources.Limits.Memory = memory
		}
		if cpu, ok := resources["cpu"].(string); ok {
			spec.Resources.Limits.CPU = cpu
		} else if cpu, ok := resources["cpu"].(float64); ok {
			spec.Resources.Limits.CPU = fmt.Sprintf("%f", cpu)
		}
	}
}

func applyEnvironment(spec *BackendInstanceSpec, jsonSpec map[string]any) {
	if environment, exists := jsonSpec["environment"]; exists {
		if values, ok := stringMap(environment); ok {
			spec.Environment = values
		}
	}
	if values, exists := jsonSpec["env_vars"]; exists {
		environment, ok := stringMap(values)
		if !ok {
			return
		}
		if spec.Environment == nil {
			spec.Environment = make(map[string]string)
		}
		for key, value := range environment {
			spec.Environment[key] = value
		}
	}
}

func applyLabels(spec *BackendInstanceSpec, jsonSpec map[string]any) {
	if labels, exists := jsonSpec["labels"]; exists {
		if values, ok := stringMap(labels); ok {
			spec.Labels = values
		}
	}
}

func stringMap(raw any) (map[string]string, bool) {
	switch values := raw.(type) {
	case map[string]any:
		out := make(map[string]string, len(values))
		for key, value := range values {
			out[key] = fmt.Sprintf("%v", value)
		}
		return out, true
	case map[string]string:
		out := make(map[string]string, len(values))
		for key, value := range values {
			out[key] = value
		}
		return out, true
	default:
		return nil, false
	}
}
