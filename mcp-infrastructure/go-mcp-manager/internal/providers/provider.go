package providers

import (
	"context"

	"github.com/agentarea/mcp-manager/internal/models"
)

// Provider defines the interface for MCP server providers
type Provider interface {
	CreateInstance(ctx context.Context, instance *models.MCPServerInstance) error
	DeleteInstance(ctx context.Context, instanceID, name string) error
}

// ProviderManager manages different types of MCP providers
type ProviderManager struct {
	dockerProvider *DockerProvider
	urlProvider    *URLProvider
}

// NewProviderManager creates a new provider manager
func NewProviderManager(dockerProvider *DockerProvider, urlProvider *URLProvider) *ProviderManager {
	return &ProviderManager{
		dockerProvider: dockerProvider,
		urlProvider:    urlProvider,
	}
}

// GetProvider returns the appropriate provider based on the instance type
func (pm *ProviderManager) GetProvider(instance *models.MCPServerInstance) (Provider, error) {
	// Check the type in json_spec
	if typeInterface, exists := instance.JSONSpec["type"]; exists {
		if typeStr, ok := typeInterface.(string); ok {
			switch typeStr {
			case "docker":
				return pm.dockerProvider, nil
			case "url":
				return pm.urlProvider, nil
			default:
				// Default to docker if type is not recognized
				return pm.dockerProvider, nil
			}
		}
	}

	// Default to docker provider if no type specified
	return pm.dockerProvider, nil
}
