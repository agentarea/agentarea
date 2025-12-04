package proxy

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/agentarea/mcp-manager/internal/config"
)

// RouteManager manages MCP service routes for the proxy
// This replaces the previous Traefik manager integration
type RouteManager struct {
	proxy  *ProxyServer
	logger *slog.Logger
	config *config.Config
}

// NewRouteManager creates a new route manager
func NewRouteManager(proxy *ProxyServer, cfg *config.Config, logger *slog.Logger) *RouteManager {
	return &RouteManager{
		proxy:  proxy,
		logger: logger,
		config: cfg,
	}
}

// AddMCPService adds a new MCP service route to the proxy
func (rm *RouteManager) AddMCPService(ctx context.Context, slug, containerIP string, containerPort int) error {
	if slug == "" {
		return fmt.Errorf("slug cannot be empty")
	}
	if containerIP == "" {
		return fmt.Errorf("container IP cannot be empty")
	}
	if containerPort <= 0 || containerPort > 65535 {
		return fmt.Errorf("invalid container port: %d", containerPort)
	}

	if err := rm.proxy.AddRoute(slug, containerIP, containerPort); err != nil {
		return fmt.Errorf("failed to add proxy route: %w", err)
	}

	rm.logger.Info("Added proxy route for MCP service",
		slog.String("slug", slug),
		slog.String("container_ip", containerIP),
		slog.Int("port", containerPort))

	return nil
}

// RemoveMCPService removes an MCP service route from the proxy
func (rm *RouteManager) RemoveMCPService(ctx context.Context, slug string) error {
	if slug == "" {
		return fmt.Errorf("slug cannot be empty")
	}

	rm.proxy.RemoveRoute(slug)

	rm.logger.Info("Removed proxy route for MCP service",
		slog.String("slug", slug))

	return nil
}
