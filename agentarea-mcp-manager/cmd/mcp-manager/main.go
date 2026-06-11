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
	"github.com/agentarea/mcp-manager/internal/features"
	"github.com/agentarea/mcp-manager/internal/providers"
	"github.com/agentarea/mcp-manager/internal/secrets"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

const version = "0.0.12"

// backendAdapter adapts the backends.Backend interface to providers.Backend interface
// to avoid import cycles between providers and backends packages
type backendAdapter struct {
	inner backends.Backend
}

func (a *backendAdapter) CreateInstance(ctx context.Context, spec *providers.BackendInstanceSpec) (*providers.BackendInstanceResult, error) {
	// Convert providers spec to backends spec
	innerSpec := &backends.InstanceSpec{
		InstanceID:  spec.InstanceID,
		Name:        spec.Name,
		ServiceName: spec.ServiceName,
		Image:       spec.Image,
		Port:        spec.Port,
		Environment: spec.Environment,
		Labels:      spec.Labels,
		Command:     spec.Command,
		Resources: backends.ResourceRequirements{
			Limits: backends.ResourceList{
				CPU:    spec.Resources.Limits.CPU,
				Memory: spec.Resources.Limits.Memory,
			},
			Requests: backends.ResourceList{
				CPU:    spec.Resources.Requests.CPU,
				Memory: spec.Resources.Requests.Memory,
			},
		},
	}

	result, err := a.inner.CreateInstance(ctx, innerSpec)
	if err != nil {
		return nil, err
	}

	return &providers.BackendInstanceResult{
		ID:     result.ID,
		Name:   result.Name,
		URL:    result.URL,
		Status: result.Status,
	}, nil
}

func (a *backendAdapter) DeleteInstance(ctx context.Context, instanceID string) error {
	return a.inner.DeleteInstance(ctx, instanceID)
}

func main() {
	// Load configuration
	cfg := config.Load()

	// Setup logging
	logger := setupLogging(cfg)

	// Initialize feature service
	featureConfig := &features.Config{
		Enabled:  cfg.Features.Enabled,
		Variants: cfg.Features.Variants,
	}
	configProvider := features.NewConfigProvider(logger, featureConfig)
	envProvider := features.NewEnvironmentProvider(logger, "MCP_FEATURE")
	hybridProvider := features.NewHybridProvider(logger, envProvider, configProvider)
	featureService := features.NewService(logger, hybridProvider)
	features.InitDefaultService(logger, hybridProvider)

	// Log enabled features
	for _, f := range features.AllFeatures {
		if featureService.IsEnabled(f) {
			logger.Info("Feature enabled", slog.String("feature", string(f)))
		}
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

		// Initialize Docker backend (Traefik handles routing via container labels)
		if err := backend.Initialize(ctx); err != nil {
			logger.Error("Failed to initialize Docker backend", slog.String("error", err.Error()))
			os.Exit(1)
		}

	default:
		logger.Error("Unsupported environment type", slog.String("type", envType))
		os.Exit(1)
	}

	// Initialize secret resolver with Infisical SDK
	secretResolver, err := secrets.NewSecretResolver(logger)
	if err != nil {
		logger.Error("Failed to initialize secret resolver", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer secretResolver.Close()

	// Wire secret resolver into container manager for SyncInstancesFromDatabase
	if containerManager != nil {
		containerManager.SetSecretResolver(secretResolver)
	}

	// Initialize providers based on environment
	var providerManager *providers.ProviderManager
	urlProvider := providers.NewURLProvider(logger)

	if envType == "docker" && containerManager != nil {
		dockerProvider := providers.NewDockerProvider(secretResolver, containerManager, logger)
		providerManager = providers.NewProviderManager(dockerProvider, nil, urlProvider)
	} else if envType == "kubernetes" {
		// For Kubernetes, create a Kubernetes provider that uses the backend
		adapter := &backendAdapter{inner: backend}
		kubernetesProvider := providers.NewKubernetesProvider(adapter, logger)
		providerManager = providers.NewProviderManager(nil, kubernetesProvider, urlProvider)
	} else {
		// Fallback - only URL provider
		providerManager = providers.NewProviderManager(nil, nil, urlProvider)
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
	handler := api.NewHandler(backend, containerManager, logger, version)
	handler.SetupRoutes(router)

	if features.IsEnabled(features.WarmPool) {
		if k8sBackend, ok := backend.(*backends.KubernetesBackend); ok {
			if wpClient := k8sBackend.GetWarmPoolClient(); wpClient != nil {
				startSandboxWorkflowGC(ctx, logger, wpClient)
			}
		}
	}

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

func startSandboxWorkflowGC(ctx context.Context, logger *slog.Logger, client *warmpool.Client) {
	interval := getDurationEnv("SANDBOX_WORKFLOW_GC_INTERVAL", 30*time.Second)
	if interval <= 0 {
		logger.Info("Sandbox workflow GC disabled")
		return
	}

	logger.Info("Starting sandbox workflow GC", slog.Duration("interval", interval))
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case now := <-ticker.C:
				deleted, err := client.DeleteExpiredWorkflowPods(ctx, now.UTC())
				if err != nil {
					logger.Warn("Sandbox workflow GC failed", slog.String("error", err.Error()))
					continue
				}
				if deleted > 0 {
					logger.Info("Sandbox workflow GC deleted expired pods", slog.Int("deleted", deleted))
				}
			}
		}
	}()
}

func getDurationEnv(name string, fallback time.Duration) time.Duration {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	duration, err := time.ParseDuration(value)
	if err != nil {
		return fallback
	}
	return duration
}
