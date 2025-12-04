package proxy

import (
	"fmt"
	"sync"
)

// ProxyRoute represents a route to an MCP container
type ProxyRoute struct {
	Slug          string
	ContainerIP   string
	ContainerPort int
}

// RouteRegistry manages all active proxy routes
type RouteRegistry struct {
	mu     sync.RWMutex
	routes map[string]*ProxyRoute
}

// NewRouteRegistry creates a new route registry
func NewRouteRegistry() *RouteRegistry {
	return &RouteRegistry{
		routes: make(map[string]*ProxyRoute),
	}
}

// AddRoute adds or updates a route in the registry
func (r *RouteRegistry) AddRoute(slug, containerIP string, containerPort int) error {
	if slug == "" {
		return fmt.Errorf("slug cannot be empty")
	}
	if containerIP == "" {
		return fmt.Errorf("container IP cannot be empty")
	}
	if containerPort <= 0 || containerPort > 65535 {
		return fmt.Errorf("invalid container port: %d", containerPort)
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	r.routes[slug] = &ProxyRoute{
		Slug:          slug,
		ContainerIP:   containerIP,
		ContainerPort: containerPort,
	}

	return nil
}

// RemoveRoute removes a route from the registry
func (r *RouteRegistry) RemoveRoute(slug string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	delete(r.routes, slug)
}

// GetRoute retrieves a route by slug
func (r *RouteRegistry) GetRoute(slug string) (*ProxyRoute, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	route, exists := r.routes[slug]
	if !exists {
		return nil, fmt.Errorf("route not found for slug: %s", slug)
	}

	return route, nil
}

// GetAllRoutes returns all registered routes
func (r *RouteRegistry) GetAllRoutes() map[string]*ProxyRoute {
	r.mu.RLock()
	defer r.mu.RUnlock()

	// Return a copy to prevent external modification
	routes := make(map[string]*ProxyRoute, len(r.routes))
	for k, v := range r.routes {
		routes[k] = v
	}
	return routes
}

// Clear removes all routes
func (r *RouteRegistry) Clear() {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.routes = make(map[string]*ProxyRoute)
}
