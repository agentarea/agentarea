package caddy

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

// Client manages communication with Caddy API
type Client struct {
	config     *config.Config
	httpClient *http.Client
	routes     map[string]models.CaddyRoute
	mutex      sync.RWMutex
}

// NewClient creates a new Caddy API client
func NewClient(cfg *config.Config) *Client {
	return &Client{
		config: cfg,
		httpClient: &http.Client{
			Timeout: cfg.Caddy.Timeout,
		},
		routes: make(map[string]models.CaddyRoute),
	}
}

// Initialize waits for Caddy to be ready and initializes the client
func (c *Client) Initialize(ctx context.Context) error {
	// Wait for Caddy to be ready
	if err := c.waitForCaddy(ctx); err != nil {
		return fmt.Errorf("caddy not ready: %w", err)
	}

	return nil
}

// waitForCaddy waits for Caddy API to be available
func (c *Client) waitForCaddy(ctx context.Context) error {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	timeout := time.After(30 * time.Second)

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timeout:
			return fmt.Errorf("timeout waiting for Caddy API")
		case <-ticker.C:
			if err := c.checkHealth(); err == nil {
				return nil
			}
		}
	}
}

// checkHealth checks if Caddy API is responding
func (c *Client) checkHealth() error {
	url := fmt.Sprintf("%s/config/", c.config.Caddy.APIURL)
	resp, err := c.httpClient.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("caddy API returned status %d", resp.StatusCode)
	}

	return nil
}

// AddService adds a new service route to Caddy
func (c *Client) AddService(serviceName string, port int) error {
	c.mutex.Lock()
	defer c.mutex.Unlock()

	serviceHost := c.config.GetServiceHost(serviceName)
	containerName := c.config.GetContainerName(serviceName)

	route := models.CaddyRoute{
		Match: []models.CaddyMatch{
			{
				Host: []string{serviceHost},
			},
		},
		Handle: []models.CaddyHandle{
			{
				Handler: "reverse_proxy",
				Upstreams: []models.CaddyUpstream{
					{
						Dial: fmt.Sprintf("%s:%d", containerName, port),
					},
				},
			},
		},
	}

	// Add route via Caddy API
	if err := c.addRouteToServer(route); err != nil {
		return fmt.Errorf("failed to add route: %w", err)
	}

	c.routes[serviceName] = route
	return nil
}

// RemoveService removes a service route from Caddy
func (c *Client) RemoveService(serviceName string) error {
	c.mutex.Lock()
	defer c.mutex.Unlock()

	if _, exists := c.routes[serviceName]; !exists {
		return nil // Route doesn't exist, nothing to remove
	}

	serviceHost := c.config.GetServiceHost(serviceName)

	// Get current routes
	routes, err := c.getRoutes()
	if err != nil {
		return fmt.Errorf("failed to get routes: %w", err)
	}

	// Filter out the route for this service
	var updatedRoutes []models.CaddyRoute
	for _, route := range routes {
		if len(route.Match) > 0 && len(route.Match[0].Host) > 0 {
			// Check if this route is for our service
			isOurRoute := false
			for _, host := range route.Match[0].Host {
				if host == serviceHost {
					isOurRoute = true
					break
				}
			}
			if !isOurRoute {
				updatedRoutes = append(updatedRoutes, route)
			}
		} else {
			updatedRoutes = append(updatedRoutes, route)
		}
	}

	// Update routes
	if err := c.updateRoutes(updatedRoutes); err != nil {
		return fmt.Errorf("failed to update routes: %w", err)
	}

	delete(c.routes, serviceName)
	return nil
}

// GetStatus returns the current status of Caddy
func (c *Client) GetStatus() models.CaddyStatusResponse {
	c.mutex.RLock()
	defer c.mutex.RUnlock()

	services := make([]string, 0, len(c.routes))
	for service := range c.routes {
		services = append(services, service)
	}

	status := "running"
	if err := c.checkHealth(); err != nil {
		status = "error"
	}

	return models.CaddyStatusResponse{
		Status:      status,
		RoutesCount: len(c.routes),
		Services:    services,
		APIURL:      c.config.Caddy.APIURL,
		CaddyHost:   c.config.Caddy.Host,
	}
}

// ListServices returns a list of configured services
func (c *Client) ListServices() []string {
	c.mutex.RLock()
	defer c.mutex.RUnlock()

	services := make([]string, 0, len(c.routes))
	for service := range c.routes {
		services = append(services, service)
	}
	return services
}

// addRouteToServer adds a route to the default server
func (c *Client) addRouteToServer(route models.CaddyRoute) error {
	url := fmt.Sprintf("%s/config/apps/http/servers/srv0/routes", c.config.Caddy.APIURL)

	body, err := json.Marshal(route)
	if err != nil {
		return err
	}

	resp, err := c.httpClient.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("caddy API returned status %d: %s", resp.StatusCode, string(body))
	}

	return nil
}

// getRoutes gets current routes from Caddy
func (c *Client) getRoutes() ([]models.CaddyRoute, error) {
	url := fmt.Sprintf("%s/config/apps/http/servers/srv0/routes", c.config.Caddy.APIURL)

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("caddy API returned status %d", resp.StatusCode)
	}

	var routes []models.CaddyRoute
	if err := json.NewDecoder(resp.Body).Decode(&routes); err != nil {
		return nil, err
	}

	return routes, nil
}

// updateRoutes updates the routes in Caddy
func (c *Client) updateRoutes(routes []models.CaddyRoute) error {
	url := fmt.Sprintf("%s/config/apps/http/servers/srv0/routes", c.config.Caddy.APIURL)

	body, err := json.Marshal(routes)
	if err != nil {
		return err
	}

	req, err := http.NewRequest(http.MethodPut, url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("caddy API returned status %d: %s", resp.StatusCode, string(body))
	}

	return nil
}
