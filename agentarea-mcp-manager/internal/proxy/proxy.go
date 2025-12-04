package proxy

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"
)

// ProxyServer serves as the HTTP reverse proxy for MCP containers
type ProxyServer struct {
	server   *http.Server
	registry *RouteRegistry
	logger   *slog.Logger
	config   ProxyConfig
}

// ProxyConfig contains configuration for the proxy server
type ProxyConfig struct {
	Port              int           // Port to listen on (default 80)
	ManagerServiceURL string        // URL of the MCP Manager service for non-MCP requests
	ReadTimeout       time.Duration // HTTP read timeout
	WriteTimeout      time.Duration // HTTP write timeout
	IdleTimeout       time.Duration // HTTP idle timeout
}

// NewProxyServer creates a new proxy server
func NewProxyServer(cfg ProxyConfig, logger *slog.Logger) *ProxyServer {
	if cfg.Port == 0 {
		cfg.Port = 80
	}
	if cfg.ReadTimeout == 0 {
		cfg.ReadTimeout = 15 * time.Second
	}
	if cfg.WriteTimeout == 0 {
		cfg.WriteTimeout = 15 * time.Second
	}
	if cfg.IdleTimeout == 0 {
		cfg.IdleTimeout = 60 * time.Second
	}

	registry := NewRouteRegistry()

	ps := &ProxyServer{
		registry: registry,
		logger:   logger,
		config:   cfg,
	}

	// Create the HTTP server with the proxy handler
	ps.server = &http.Server{
		Addr:         fmt.Sprintf(":%d", cfg.Port),
		Handler:      ps.handler(),
		ReadTimeout:  cfg.ReadTimeout,
		WriteTimeout: cfg.WriteTimeout,
		IdleTimeout:  cfg.IdleTimeout,
	}

	return ps
}

// handler returns the HTTP handler with routing logic
func (ps *ProxyServer) handler() http.Handler {
	return http.HandlerFunc(ps.handleRequest)
}

// handleRequest is the main request handler
func (ps *ProxyServer) handleRequest(w http.ResponseWriter, r *http.Request) {
	// Extract slug from path
	slug, hasSlug := ps.extractSlug(r.URL.Path)

	if hasSlug {
		// Try to find route for MCP service
		route, err := ps.registry.GetRoute(slug)
		if err == nil {
			// Route found, forward to container
			ps.forwardToContainer(w, r, route)
			return
		}
		// Route not found, log and continue to default handling
		ps.logger.Debug("Route not found for slug", slog.String("slug", slug))
	}

	// No MCP route matched, forward to manager service
	ps.forwardToManagerService(w, r)
}

// extractSlug extracts the slug from a /mcp/{slug}/... path
// Returns (slug, found)
func (ps *ProxyServer) extractSlug(path string) (string, bool) {
	// Check if path starts with /mcp/
	if !strings.HasPrefix(path, "/mcp/") {
		return "", false
	}

	// Remove /mcp/ prefix
	remaining := strings.TrimPrefix(path, "/mcp/")

	// Extract slug (everything before the next /)
	parts := strings.SplitN(remaining, "/", 2)
	if len(parts) == 0 || parts[0] == "" {
		return "", false
	}

	return parts[0], true
}

// forwardToContainer forwards the request to the MCP container
func (ps *ProxyServer) forwardToContainer(w http.ResponseWriter, r *http.Request, route *ProxyRoute) {
	// Build target URL by removing /mcp/{slug} prefix and keeping the rest
	targetPath := ps.stripMCPPrefix(r.URL.Path, route.Slug)

	// Create target URL
	targetURL := &url.URL{
		Scheme:   "http",
		Host:     fmt.Sprintf("%s:%d", route.ContainerIP, route.ContainerPort),
		Path:     targetPath,
		RawQuery: r.URL.RawQuery,
	}

	// Create reverse proxy
	director := func(req *http.Request) {
		req.URL = targetURL
		req.RequestURI = ""
		req.Host = targetURL.Host
		req.Header.Set("X-Forwarded-For", ps.getClientIP(r))
		req.Header.Set("X-Forwarded-Proto", "http")
		req.Header.Set("X-Forwarded-Host", r.Host)
		req.Header.Set("X-Forwarded-Path", r.URL.Path)
	}

	proxy := &httputil.ReverseProxy{
		Director:  director,
		Transport: ps.createTransport(),
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			ps.logger.Error("Proxy error",
				slog.String("slug", route.Slug),
				slog.String("target", targetURL.String()),
				slog.String("error", err.Error()))
			http.Error(w, "Bad Gateway", http.StatusBadGateway)
		},
	}

	ps.logger.Debug("Forwarding request to container",
		slog.String("slug", route.Slug),
		slog.String("target", targetURL.String()),
		slog.String("path", r.URL.Path))

	proxy.ServeHTTP(w, r)
}

// stripMCPPrefix removes /mcp/{slug} from the path
func (ps *ProxyServer) stripMCPPrefix(path string, slug string) string {
	prefix := fmt.Sprintf("/mcp/%s", slug)
	remaining := strings.TrimPrefix(path, prefix)

	// If no remaining path, return /
	if remaining == "" {
		return "/"
	}

	return remaining
}

// forwardToManagerService forwards non-MCP requests to the manager service
func (ps *ProxyServer) forwardToManagerService(w http.ResponseWriter, r *http.Request) {
	if ps.config.ManagerServiceURL == "" {
		ps.logger.Error("Manager service URL not configured")
		http.Error(w, "Service Unavailable", http.StatusServiceUnavailable)
		return
	}

	targetURL, err := url.Parse(ps.config.ManagerServiceURL)
	if err != nil {
		ps.logger.Error("Invalid manager service URL", slog.String("error", err.Error()))
		http.Error(w, "Service Unavailable", http.StatusServiceUnavailable)
		return
	}

	// Preserve original path and query
	targetURL.Path = r.URL.Path
	targetURL.RawQuery = r.URL.RawQuery

	director := func(req *http.Request) {
		req.URL = targetURL
		req.RequestURI = ""
		req.Host = targetURL.Host
		req.Header.Set("X-Forwarded-For", ps.getClientIP(r))
		req.Header.Set("X-Forwarded-Proto", "http")
		req.Header.Set("X-Forwarded-Host", r.Host)
	}

	proxy := &httputil.ReverseProxy{
		Director:  director,
		Transport: ps.createTransport(),
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			ps.logger.Error("Manager service proxy error",
				slog.String("target", targetURL.String()),
				slog.String("error", err.Error()))
			http.Error(w, "Bad Gateway", http.StatusBadGateway)
		},
	}

	ps.logger.Debug("Forwarding request to manager service",
		slog.String("target", targetURL.String()),
		slog.String("path", r.URL.Path))

	proxy.ServeHTTP(w, r)
}

// createTransport creates an HTTP transport with optimized settings
func (ps *ProxyServer) createTransport() *http.Transport {
	return &http.Transport{
		Dial: (&net.Dialer{
			Timeout:   10 * time.Second,
			KeepAlive: 30 * time.Second,
		}).Dial,
		MaxIdleConns:        100,
		MaxIdleConnsPerHost: 100,
		IdleConnTimeout:     90 * time.Second,
		DisableCompression:  false,
	}
}

// getClientIP extracts the client IP from the request
func (ps *ProxyServer) getClientIP(r *http.Request) string {
	// Check X-Forwarded-For first (for proxied requests)
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		// Take the first IP in the chain
		ips := strings.Split(xff, ",")
		return strings.TrimSpace(ips[0])
	}

	// Check X-Real-IP
	if xri := r.Header.Get("X-Real-IP"); xri != "" {
		return xri
	}

	// Fall back to RemoteAddr
	if ip, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		return ip
	}

	return r.RemoteAddr
}

// AddRoute adds a route to the proxy
func (ps *ProxyServer) AddRoute(slug, containerIP string, containerPort int) error {
	return ps.registry.AddRoute(slug, containerIP, containerPort)
}

// RemoveRoute removes a route from the proxy
func (ps *ProxyServer) RemoveRoute(slug string) {
	ps.registry.RemoveRoute(slug)
}

// GetRoute retrieves a route
func (ps *ProxyServer) GetRoute(slug string) (*ProxyRoute, error) {
	return ps.registry.GetRoute(slug)
}

// GetAllRoutes returns all routes
func (ps *ProxyServer) GetAllRoutes() map[string]*ProxyRoute {
	return ps.registry.GetAllRoutes()
}

// Start starts the proxy server
func (ps *ProxyServer) Start() error {
	ps.logger.Info("Starting proxy server", slog.Int("port", ps.config.Port))
	return ps.server.ListenAndServe()
}

// Shutdown gracefully shuts down the proxy server
func (ps *ProxyServer) Shutdown(ctx context.Context) error {
	ps.logger.Info("Shutting down proxy server")
	return ps.server.Shutdown(ctx)
}
