package container

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"

	yaml "gopkg.in/yaml.v3"

	"github.com/agentarea/mcp-manager/internal/config"
)

// TraefikConfig represents the dynamic Traefik configuration
type TraefikConfig struct {
	HTTP TraefikHTTP `yaml:"http"`
}

type TraefikHTTP struct {
	Routers     map[string]TraefikRouter     `yaml:"routers"`
	Services    map[string]TraefikService    `yaml:"services"`
	Middlewares map[string]TraefikMiddleware `yaml:"middlewares"`
}

type TraefikRouter struct {
	Rule        string   `yaml:"rule"`
	Service     string   `yaml:"service"`
	EntryPoints []string `yaml:"entryPoints"`
	Middlewares []string `yaml:"middlewares,omitempty"`
}

type TraefikService struct {
	LoadBalancer TraefikLoadBalancer `yaml:"loadBalancer"`
}

type TraefikLoadBalancer struct {
	Servers []TraefikServer `yaml:"servers"`
}

type TraefikServer struct {
	URL string `yaml:"url"`
}

type TraefikMiddleware struct {
	StripPrefix *TraefikStripPrefix `yaml:"stripPrefix,omitempty"`
}

type TraefikStripPrefix struct {
	Prefixes   []string `yaml:"prefixes"`
	ForceSlash bool     `yaml:"forceSlash"`
}

// TraefikManager manages Traefik configuration
type TraefikManager struct {
	configPath string
	logger     *slog.Logger
	config     *config.Config
}

// NewTraefikManager creates a new Traefik manager
func NewTraefikManager(cfg *config.Config, logger *slog.Logger) *TraefikManager {
	return &TraefikManager{
		configPath: "/etc/traefik/dynamic.yml",
		logger:     logger,
		config:     cfg,
	}
}

// AddMCPService adds a new MCP service route to Traefik
func (tm *TraefikManager) AddMCPService(ctx context.Context, slug, containerIP string, containerPort int) error {
	config, err := tm.loadConfig()
	if err != nil {
		return fmt.Errorf("failed to load config: %w", err)
	}

	// Add router for the MCP service using slug
	routerName := fmt.Sprintf("mcp-%s", slug)
	config.HTTP.Routers[routerName] = TraefikRouter{
		Rule:        fmt.Sprintf("PathPrefix(`/mcp/%s`)", slug),
		Service:     fmt.Sprintf("mcp-%s-service", slug),
		EntryPoints: []string{"web"},
		Middlewares: []string{fmt.Sprintf("mcp-%s-stripprefix", slug)},
	}

	// Add service for the MCP service
	serviceNameFull := fmt.Sprintf("mcp-%s-service", slug)
	config.HTTP.Services[serviceNameFull] = TraefikService{
		LoadBalancer: TraefikLoadBalancer{
			Servers: []TraefikServer{
				{URL: fmt.Sprintf("http://%s:%d", containerIP, containerPort)},
			},
		},
	}

	// Add middleware to strip prefix
	middlewareName := fmt.Sprintf("mcp-%s-stripprefix", slug)
	config.HTTP.Middlewares[middlewareName] = TraefikMiddleware{
		StripPrefix: &TraefikStripPrefix{
			Prefixes:   []string{fmt.Sprintf("/mcp/%s", slug)},
			ForceSlash: false,
		},
	}

	// Save updated configuration
	if err := tm.saveConfig(config); err != nil {
		return fmt.Errorf("failed to save config: %w", err)
	}

	tm.logger.Info("Added Traefik route for MCP service",
		slog.String("slug", slug),
		slog.String("container_ip", containerIP),
		slog.Int("port", containerPort))

	return nil
}

// RemoveMCPService removes an MCP service route from Traefik
func (tm *TraefikManager) RemoveMCPService(ctx context.Context, slug string) error {
	config, err := tm.loadConfig()
	if err != nil {
		return fmt.Errorf("failed to load config: %w", err)
	}

	// Remove router, service, and middleware using slug
	routerName := fmt.Sprintf("mcp-%s", slug)
	serviceNameFull := fmt.Sprintf("mcp-%s-service", slug)
	middlewareName := fmt.Sprintf("mcp-%s-stripprefix", slug)

	delete(config.HTTP.Routers, routerName)
	delete(config.HTTP.Services, serviceNameFull)
	delete(config.HTTP.Middlewares, middlewareName)

	// Save updated configuration
	if err := tm.saveConfig(config); err != nil {
		return fmt.Errorf("failed to save config: %w", err)
	}

	tm.logger.Info("Removed Traefik route for MCP service",
		slog.String("slug", slug))

	return nil
}

// LoadConfig loads the current Traefik configuration
func (tm *TraefikManager) LoadConfig() (*TraefikConfig, error) {
	config := &TraefikConfig{
		HTTP: TraefikHTTP{
			Routers:     make(map[string]TraefikRouter),
			Services:    make(map[string]TraefikService),
			Middlewares: make(map[string]TraefikMiddleware),
		},
	}

	// Check if config file exists
	if _, err := os.Stat(tm.configPath); os.IsNotExist(err) {
		// Create default configuration
		return tm.createDefaultConfig()
	}

	// Read existing configuration
	data, err := os.ReadFile(tm.configPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	if err := yaml.Unmarshal(data, config); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	// Initialize maps if they're nil
	if config.HTTP.Routers == nil {
		config.HTTP.Routers = make(map[string]TraefikRouter)
	}
	if config.HTTP.Services == nil {
		config.HTTP.Services = make(map[string]TraefikService)
	}
	if config.HTTP.Middlewares == nil {
		config.HTTP.Middlewares = make(map[string]TraefikMiddleware)
	}

	return config, nil
}

// loadConfig loads the current Traefik configuration (private version)
func (tm *TraefikManager) loadConfig() (*TraefikConfig, error) {
	return tm.LoadConfig()
}

// saveConfig saves the Traefik configuration to file
func (tm *TraefikManager) saveConfig(config *TraefikConfig) error {
	// Ensure directory exists
	if err := os.MkdirAll(filepath.Dir(tm.configPath), 0755); err != nil {
		return fmt.Errorf("failed to create config directory: %w", err)
	}

	data, err := yaml.Marshal(config)
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}

	if err := os.WriteFile(tm.configPath, data, 0644); err != nil {
		return fmt.Errorf("failed to write config file: %w", err)
	}

	return nil
}

// createDefaultConfig creates the default Traefik configuration
func (tm *TraefikManager) createDefaultConfig() (*TraefikConfig, error) {
	config := &TraefikConfig{
		HTTP: TraefikHTTP{
			Routers: map[string]TraefikRouter{
				"mcp-manager-health": {
					Rule:        "Path(`/health`)",
					Service:     "mcp-manager-service",
					EntryPoints: []string{"web"},
				},
				"mcp-manager-api": {
					Rule:        "PathPrefix(`/api/mcp`)",
					Service:     "mcp-manager-service",
					EntryPoints: []string{"web"},
					Middlewares: []string{"mcp-api-stripprefix"},
				},
				"mcp-manager-catchall": {
					Rule:        "!PathPrefix(`/mcp/`) && !PathPrefix(`/api/mcp`)",
					Service:     "mcp-manager-service",
					EntryPoints: []string{"web"},
				},
			},
			Services: map[string]TraefikService{
				"mcp-manager-service": {
					LoadBalancer: TraefikLoadBalancer{
						Servers: []TraefikServer{
							{URL: tm.config.Traefik.ManagerServiceURL},
						},
					},
				},
			},
			Middlewares: map[string]TraefikMiddleware{
				"mcp-stripprefix": {
					StripPrefix: &TraefikStripPrefix{
						Prefixes:   []string{"/mcp"},
						ForceSlash: false,
					},
				},
				"mcp-api-stripprefix": {
					StripPrefix: &TraefikStripPrefix{
						Prefixes:   []string{"/api/mcp"},
						ForceSlash: false,
					},
				},
			},
		},
	}

	if err := tm.saveConfig(config); err != nil {
		return nil, fmt.Errorf("failed to save default config: %w", err)
	}

	return config, nil
}
