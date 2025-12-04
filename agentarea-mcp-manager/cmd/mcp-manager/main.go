package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/api"
	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/container"
	"github.com/agentarea/mcp-manager/internal/environment"
	"github.com/agentarea/mcp-manager/internal/events"
	"github.com/agentarea/mcp-manager/internal/providers"
	"github.com/agentarea/mcp-manager/internal/proxy"
	"github.com/agentarea/mcp-manager/internal/secrets"
	"github.com/agentarea/mcp-manager/internal/templates"
)

const version = "0.1.0"

func main() {
	// Load configuration
	cfg := config.Load()

	// Setup logging
	logger := setupLogging(cfg)

	// Initialize template loader
	templateLoader := templates.NewLoader(cfg.MCPProvidersPath)
	if err := templateLoader.Load(); err != nil {
		logger.Warn("Failed to load MCP templates",
			slog.String("path", cfg.MCPProvidersPath),
			slog.String("error", err.Error()))
	} else {
		logger.Info("Loaded MCP templates",
			slog.Int("count", len(templateLoader.List())))
	}

	// Create context for graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Detect environment and initialize appropriate backend
	var backend backends.Backend
	var containerManager *container.Manager

	if cfg.Environment != "" {
		logger.Info("Using forced environment", slog.String("environment", cfg.Environment))
	}

	envType := environment.DetectEnvironment(cfg.Environment, logger)
	logger.Info("Environment detected", slog.String("type", envType))

	switch envType {
	case "kubernetes":
		logger.Info("Initializing Kubernetes backend")
		k8sBackend, err := backends.NewKubernetesBackend(cfg, logger)
		if err != nil {
			logger.Error("Failed to create Kubernetes backend", slog.String("error", err.Error()))
			os.Exit(1)
		}
		backend = k8sBackend

		// Initialize Kubernetes backend
		if err := backend.Initialize(ctx); err != nil {
			logger.Error("Failed to initialize Kubernetes backend", slog.String("error", err.Error()))
			os.Exit(1)
		}

	case "docker":
		logger.Info("Initializing Docker backend")
		dockerBackend := backends.NewDockerBackend(cfg, logger)
		backend = dockerBackend

		// Get the container manager from the docker backend for compatibility
		containerManager = dockerBackend.GetManager()

		// Initialize Docker backend
		if err := backend.Initialize(ctx); err != nil {
			logger.Error("Failed to initialize Docker backend", slog.String("error", err.Error()))
			os.Exit(1)
		}

	default:
		logger.Error("Unsupported environment type", slog.String("type", envType))
		os.Exit(1)
	}

	// Start internal proxy server in background only for Docker environments
	var proxyServer *proxy.ProxyServer
	var routeManager *proxy.RouteManager
	if envType == "docker" {
		proxyConfig := proxy.ProxyConfig{
			Port:              80,
			ManagerServiceURL: cfg.Traefik.ManagerServiceURL,
			ReadTimeout:       15 * time.Second,
			WriteTimeout:      15 * time.Second,
			IdleTimeout:       60 * time.Second,
		}
		proxyServer = proxy.NewProxyServer(proxyConfig, logger)
		routeManager = proxy.NewRouteManager(proxyServer, cfg, logger)

		// Set the route manager in the container manager for route registration
		if containerManager != nil {
			containerManager.SetRouteManager(routeManager)
		}

		// Start proxy server in background
		go func() {
			if err := proxyServer.Start(); err != nil && err != http.ErrServerClosed {
				logger.Error("Proxy server failed", slog.String("error", err.Error()))
			}
		}()
	}

	// Initialize secret resolver with Infisical SDK
	secretResolver, err := secrets.NewSecretResolver(logger)
	if err != nil {
		logger.Error("Failed to initialize secret resolver", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer secretResolver.Close()

	// Initialize providers based on environment
	var providerManager *providers.ProviderManager
	if envType == "docker" && containerManager != nil {
		dockerProvider := providers.NewDockerProvider(secretResolver, containerManager, logger)
		urlProvider := providers.NewURLProvider(logger)
		providerManager = providers.NewProviderManager(dockerProvider, urlProvider)
	} else {
		// For Kubernetes, we'll use the backend directly through the API
		urlProvider := providers.NewURLProvider(logger)
		providerManager = providers.NewProviderManager(nil, urlProvider)
	}

	// Initialize event subscriber
	eventSubscriber := events.NewEventSubscriber(cfg.Redis.URL, providerManager, logger)

	// Start event subscriber in a goroutine
	go func() {
		if err := eventSubscriber.Start(ctx); err != nil && err != context.Canceled {
			logger.Error("Event subscriber failed", slog.String("error", err.Error()))
		}
	}()

	// Setup HTTP router
	router := setupRouter(cfg, logger)
	handler := api.NewHandler(backend, containerManager, templateLoader, logger, version)
	handler.SetupRoutes(router)

	// Start HTTP server
	server := &http.Server{
		Addr:         fmt.Sprintf("%s:%d", cfg.Server.Host, cfg.Server.Port),
		Handler:      router,
		ReadTimeout:  cfg.Server.ReadTimeout,
		WriteTimeout: cfg.Server.WriteTimeout,
	}

	// Start server in a goroutine
	go func() {
		logger.Info("Starting MCP Manager",
			slog.String("version", version),
			slog.String("address", server.Addr))

		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("Server failed to start", slog.String("error", err.Error()))
			os.Exit(1)
		}
	}()

	// Wait for interrupt signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("Shutting down server...")

	// Graceful shutdown
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer shutdownCancel()

	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error("Server forced to shutdown", slog.String("error", err.Error()))
	}

	// Shutdown proxy server if it exists (Docker environment)
	if proxyServer != nil {
		if err := proxyServer.Shutdown(shutdownCtx); err != nil {
			logger.Error("Failed to shutdown proxy server", slog.String("error", err.Error()))
		}
	}

	// Close event subscriber
	if err := eventSubscriber.Close(); err != nil {
		logger.Error("Failed to close event subscriber", slog.String("error", err.Error()))
	}

	// Shutdown backend
	if err := backend.Shutdown(shutdownCtx); err != nil {
		logger.Error("Failed to shutdown backend", slog.String("error", err.Error()))
	}

	// Shutdown container manager if it exists (Docker environment)
	if containerManager != nil {
		if err := containerManager.Shutdown(shutdownCtx); err != nil {
			logger.Error("Failed to shutdown container manager", slog.String("error", err.Error()))
		}
	}

	logger.Info("Server shutdown complete")
}

// setupLogging configures structured logging
func setupLogging(cfg *config.Config) *slog.Logger {
	var handler slog.Handler

	opts := &slog.HandlerOptions{
		Level: getLogLevel(cfg.Logging.Level),
	}

	if cfg.Logging.Format == "json" {
		handler = slog.NewJSONHandler(os.Stdout, opts)
	} else {
		handler = slog.NewTextHandler(os.Stdout, opts)
	}

	return slog.New(handler)
}

// setupRouter configures the HTTP router
func setupRouter(cfg *config.Config, logger *slog.Logger) *gin.Engine {
	// Set Gin mode based on log level
	if cfg.Logging.Level == "DEBUG" {
		gin.SetMode(gin.DebugMode)
	} else {
		gin.SetMode(gin.ReleaseMode)
	}

	router := gin.New()

	// Add middleware
	router.Use(gin.Recovery())

	// Add logging middleware
	router.Use(gin.LoggerWithFormatter(func(param gin.LogFormatterParams) string {
		logger.Info("HTTP request",
			slog.String("method", param.Method),
			slog.String("path", param.Path),
			slog.Int("status", param.StatusCode),
			slog.Duration("latency", param.Latency),
			slog.String("ip", param.ClientIP))
		return ""
	}))

	// Add CORS middleware if enabled
	if cfg.Server.CORSEnabled {
		corsConfig := cors.DefaultConfig()
		if len(cfg.Server.CORSAllowedOrigins) > 0 {
			corsConfig.AllowOrigins = cfg.Server.CORSAllowedOrigins
		} else {
			corsConfig.AllowAllOrigins = true
		}
		corsConfig.AllowMethods = []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"}
		corsConfig.AllowHeaders = []string{"Origin", "Content-Type", "Accept", "Authorization"}
		corsConfig.ExposeHeaders = []string{"Content-Length"}
		corsConfig.AllowCredentials = true

		router.Use(cors.New(corsConfig))
		logger.Info("CORS enabled", slog.Any("allowed_origins", cfg.Server.CORSAllowedOrigins))
	} else {
		logger.Info("CORS disabled")
	}

	return router
}

// getLogLevel converts string log level to slog.Level
func getLogLevel(level string) slog.Level {
	switch level {
	case "DEBUG":
		return slog.LevelDebug
	case "INFO":
		return slog.LevelInfo
	case "WARN":
		return slog.LevelWarn
	case "ERROR":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}
