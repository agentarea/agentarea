package providers

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
)

// URLProvider handles URL-based MCP server instances
type URLProvider struct {
	logger *slog.Logger
	client *http.Client
}

// NewURLProvider creates a new URL provider
func NewURLProvider(logger *slog.Logger) *URLProvider {
	return &URLProvider{
		logger: logger,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// CreateInstance registers a URL-based MCP server (no container creation needed)
func (p *URLProvider) CreateInstance(ctx context.Context, instance *models.MCPServerInstance) error {
	spec := instance.JSONSpec

	// Extract URL-specific configuration
	endpoint, ok := spec["endpoint"].(string)
	if !ok {
		return fmt.Errorf("missing or invalid endpoint in json_spec")
	}

	p.logger.Info("Registering URL-based MCP server",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name),
		slog.String("endpoint", endpoint))

	// Validate the endpoint is reachable
	if err := p.validateEndpoint(ctx, endpoint, spec); err != nil {
		p.logger.Error("Failed to validate URL endpoint",
			slog.String("instance_id", instance.InstanceID),
			slog.String("endpoint", endpoint),
			slog.String("error", err.Error()))
		return fmt.Errorf("endpoint validation failed: %w", err)
	}

	p.logger.Info("Successfully registered URL-based MCP server",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name),
		slog.String("endpoint", endpoint))

	return nil
}

// DeleteInstance unregisters the URL-based MCP server
func (p *URLProvider) DeleteInstance(ctx context.Context, instanceID, name string) error {
	p.logger.Info("Unregistering URL-based MCP server",
		slog.String("instance_id", instanceID),
		slog.String("name", name))

	// For URL-based servers, we just log the deletion
	// In a more complex setup, we might need to remove from a registry

	p.logger.Info("Successfully unregistered URL-based MCP server",
		slog.String("instance_id", instanceID),
		slog.String("name", name))

	return nil
}

// GetInstanceStatus checks the health of the URL-based MCP server
func (p *URLProvider) GetInstanceStatus(ctx context.Context, endpoint string) (string, error) {
	// Try to make a health check request
	req, err := http.NewRequestWithContext(ctx, "GET", endpoint, nil)
	if err != nil {
		return "error", fmt.Errorf("failed to create request: %w", err)
	}

	resp, err := p.client.Do(req)
	if err != nil {
		return "unreachable", fmt.Errorf("failed to reach endpoint: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return "running", nil
	}

	return "error", fmt.Errorf("endpoint returned status %d", resp.StatusCode)
}

// validateEndpoint validates that the MCP endpoint is reachable and responds correctly
func (p *URLProvider) validateEndpoint(ctx context.Context, endpoint string, spec map[string]interface{}) error {
	// Check if there's a specific health check path
	healthPath := "/health"
	if healthCheck, exists := spec["health_check"]; exists {
		if hc, ok := healthCheck.(map[string]interface{}); ok {
			if path, exists := hc["path"]; exists {
				if pathStr, ok := path.(string); ok {
					healthPath = pathStr
				}
			}
		}
	}

	// Construct the full health check URL
	healthURL := endpoint
	if healthPath != "" && healthPath != "/" {
		healthURL = endpoint + healthPath
	}

	p.logger.Debug("Validating endpoint",
		slog.String("endpoint", endpoint),
		slog.String("health_url", healthURL))

	// Make the health check request
	req, err := http.NewRequestWithContext(ctx, "GET", healthURL, nil)
	if err != nil {
		return fmt.Errorf("failed to create health check request: %w", err)
	}

	// Add authentication if specified
	if auth, exists := spec["authentication"]; exists {
		if authMap, ok := auth.(map[string]interface{}); ok {
			if authType, exists := authMap["type"]; exists && authType == "bearer" {
				if token, exists := authMap["token"]; exists {
					if tokenStr, ok := token.(string); ok {
						req.Header.Set("Authorization", "Bearer "+tokenStr)
					}
				}
			}
		}
	}

	resp, err := p.client.Do(req)
	if err != nil {
		return fmt.Errorf("health check failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("health check returned status %d", resp.StatusCode)
	}

	return nil
}
