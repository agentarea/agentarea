package providers

import (
	"context"
	"fmt"

	"github.com/agentarea/mcp-manager/internal/models"
)

// Provider defines the interface for MCP server providers
type Provider interface {
	CreateInstance(ctx context.Context, instance *models.MCPServerInstance) error
	DeleteInstance(ctx context.Context, instanceID, name string) error
}

// ProviderManager manages different types of MCP providers
type ProviderManager struct {
	dockerProvider     *DockerProvider
	kubernetesProvider *KubernetesProvider
	urlProvider        *URLProvider
}

// NewProviderManager creates a new provider manager
func NewProviderManager(dockerProvider *DockerProvider, kubernetesProvider *KubernetesProvider, urlProvider *URLProvider) *ProviderManager {
	return &ProviderManager{
		dockerProvider:     dockerProvider,
		kubernetesProvider: kubernetesProvider,
		urlProvider:        urlProvider,
	}
}

// GetProvider returns the appropriate provider based on the instance type
func (pm *ProviderManager) GetProvider(instance *models.MCPServerInstance) (Provider, error) {
	// Check the type in json_spec
	if typeInterface, exists := instance.JSONSpec["type"]; exists {
		if typeStr, ok := typeInterface.(string); ok {
			switch typeStr {
			case "docker", "command":
				// "docker" and "command" both describe a container workload.
				// In Kubernetes mode the k8s provider handles both — fall back
				// to it when the docker provider isn't registered.
				if pm.dockerProvider != nil {
					return pm.dockerProvider, nil
				}
				if pm.kubernetesProvider != nil {
					return pm.kubernetesProvider, nil
				}
				return nil, fmt.Errorf("no container provider available (docker/kubernetes)")
			case "kubernetes":
				if pm.kubernetesProvider != nil {
					return pm.kubernetesProvider, nil
				}
				return nil, fmt.Errorf("kubernetes provider not available")
			case "url":
				if pm.urlProvider != nil {
					return pm.urlProvider, nil
				}
				return nil, fmt.Errorf("url provider not available")
			default:
				// Try providers in order: kubernetes, docker, url
				if pm.kubernetesProvider != nil {
					return pm.kubernetesProvider, nil
				}
				if pm.dockerProvider != nil {
					return pm.dockerProvider, nil
				}
				if pm.urlProvider != nil {
					return pm.urlProvider, nil
				}
				return nil, fmt.Errorf("no providers available")
			}
		}
	}

	// Default: try providers in order
	if pm.kubernetesProvider != nil {
		return pm.kubernetesProvider, nil
	}
	if pm.dockerProvider != nil {
		return pm.dockerProvider, nil
	}
	if pm.urlProvider != nil {
		return pm.urlProvider, nil
	}
	return nil, fmt.Errorf("no providers available")
}
