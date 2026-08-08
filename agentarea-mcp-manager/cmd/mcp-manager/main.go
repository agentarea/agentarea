package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/api"
	"github.com/agentarea/mcp-manager/internal/artifactstore"
	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/container"
	"github.com/agentarea/mcp-manager/internal/database"
	"github.com/agentarea/mcp-manager/internal/dataplane"
	"github.com/agentarea/mcp-manager/internal/environment"
	"github.com/agentarea/mcp-manager/internal/features"
	"github.com/agentarea/mcp-manager/internal/mcpgateway"
	"github.com/agentarea/mcp-manager/internal/providers"
	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
	"github.com/agentarea/mcp-manager/internal/sandboxplacement"
	"github.com/agentarea/mcp-manager/internal/sandboxrunner"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/secrets"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

const version = "0.0.14"

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
		IsolationTier: spec.IsolationTier,
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

func initBackend(
	ctx context.Context,
	cfg *config.Config,
	logger *slog.Logger,
	taskLeaseTTL time.Duration,
) (string, backends.Backend, *container.Manager) {
	if cfg.Environment != "" {
		logger.Info("Using forced environment", slog.String("environment", cfg.Environment))
	}

	envType, err := environment.DetectEnvironment(cfg.Environment, logger)
	if err != nil {
		logger.Error("Refusing to start", slog.String("error", err.Error()))
		os.Exit(1)
	}
	logger.Info("Environment detected", slog.String("type", envType))

	var backend backends.Backend
	var containerManager *container.Manager

	switch envType {
	case "kubernetes":
		logger.Info("Initializing Kubernetes backend")
		k8sBackend, err := backends.NewKubernetesBackend(cfg, logger, taskLeaseTTL)
		if err != nil {
			logger.Error("Failed to create Kubernetes backend", slog.String("error", err.Error()))
			os.Exit(1)
		}
		backend = k8sBackend

	case "docker":
		logger.Info("Initializing Docker backend")
		dockerBackend := backends.NewDockerBackend(cfg, logger)
		backend = dockerBackend

		// Get the container manager from the docker backend for compatibility
		containerManager = dockerBackend.GetManager()

	case "dataplane":
		logger.Info("Initializing remote data-plane backend")
		agentCfg, err := dataplane.ClientConfigFromEnv()
		if err != nil {
			logger.Error("Failed to configure remote data-plane backend", slog.String("error", err.Error()))
			os.Exit(1)
		}
		backend = dataplane.NewClient(agentCfg)
		logger.Info("Remote data-plane backend configured", slog.String("url", agentCfg.BaseURL))

	default:
		logger.Error("Unsupported environment type", slog.String("type", envType))
		os.Exit(1)
	}

	// Reachability and the token are proven here rather than on the first tool
	// call, where the failure would reach a user as a broken tool.
	if err := backend.Initialize(ctx); err != nil {
		logger.Error("Failed to initialize backend", slog.String("environment", envType), slog.String("error", err.Error()))
		os.Exit(1)
	}
	return envType, backend, containerManager
}

func initProviderManager(
	envType string,
	backend backends.Backend,
	containerManager *container.Manager,
	secretResolver secrets.SecretResolver,
	logger *slog.Logger,
) *providers.ProviderManager {
	urlProvider := providers.NewURLProvider(logger)
	switch {
	case envType == "docker" && containerManager != nil:
		dockerProvider := providers.NewDockerProvider(secretResolver, containerManager, logger)
		return providers.NewProviderManager(dockerProvider, nil, urlProvider)
	case envType == "kubernetes":
		// For Kubernetes, create a Kubernetes provider that uses the backend
		adapter := &backendAdapter{inner: backend}
		kubernetesProvider := providers.NewKubernetesProvider(adapter, secretResolver, logger)
		return providers.NewProviderManager(nil, kubernetesProvider, urlProvider)
	default:
		// Fallback - only URL provider
		return providers.NewProviderManager(nil, nil, urlProvider)
	}
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
	sandboxPolicy, err := sandboxruntime.LoadControlPolicyFromEnv()
	if err != nil {
		logger.Error("Failed to configure sandbox control policy", slog.String("error", err.Error()))
		os.Exit(1)
	}
	workspaceConfig, err := workspace.LoadConfigFromEnv()
	if err != nil {
		logger.Error("Failed to configure sandbox workspace policy", slog.String("error", err.Error()))
		os.Exit(1)
	}
	workspaceLimits := sandboxruntime.WorkspaceLimits{
		MaxFiles: workspaceConfig.MaxFiles, MaxFileBytes: workspaceConfig.MaxFileBytes, MaxBytes: workspaceConfig.MaxBytes,
	}

	// Detect environment and initialize appropriate backend
	envType, backend, containerManager := initBackend(ctx, cfg, logger, sandboxPolicy.TaskLeaseTTL)

	// Data-plane mode stops here: this process is a data plane, and everything
	// below — secrets, Redis, the event bus, the sandbox runtime — is
	// control-plane wiring that must not exist on a host running untrusted
	// containers. The check lives inside the call so main does not grow another
	// branch; it returns immediately unless data-plane mode was requested.
	serveDataPlaneAndExit(ctx, cfg, backend, logger)

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

	providerManager := initProviderManager(envType, backend, containerManager, secretResolver, logger)

	// Container-backed MCP traffic always crosses this demand boundary. It is
	// the sole owner of cold start, request leases, and idle reclamation; Python
	// only speaks ordinary MCP Streamable HTTP to the stable manager endpoint.
	gatewayPolicy, err := mcpgateway.LoadPolicyFromEnv()
	if err != nil {
		logger.Error("Failed to configure MCP demand gateway", slog.String("error", err.Error()))
		os.Exit(1)
	}
	imagePolicy, err := mcpgateway.LoadImagePolicyFromEnv()
	if err != nil {
		logger.Error("Failed to configure MCP instance admission", slog.String("error", err.Error()))
		os.Exit(1)
	}
	gatewayRepository, err := mcpgateway.OpenSQLRepository(ctx, database.BuildConnStr(logger))
	if err != nil {
		logger.Error("Failed to initialize MCP demand gateway state", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer gatewayRepository.Close()
	gatewayRuntime, err := mcpgateway.NewProviderRuntime(providerManager, backend, cfg, imagePolicy, gatewayPolicy.StartupTimeout)
	if err != nil {
		logger.Error("Failed to initialize MCP demand runtime", slog.String("error", err.Error()))
		os.Exit(1)
	}
	mcpGateway, err := mcpgateway.New(gatewayRepository, gatewayRuntime, gatewayPolicy, logger)
	if err != nil {
		logger.Error("Failed to initialize MCP demand gateway", slog.String("error", err.Error()))
		os.Exit(1)
	}

	// The MCP backend and sandbox data plane are independent. A built-in
	// sandbox provider needs the backend runtime; external providers do not.
	builtinSandboxRuntime, _ := backend.(sandboxruntime.ManagedRuntime)
	sandboxControlConfig, err := sandboxcontrol.LoadConfigFromEnv(cfg.Redis.URL)
	if err != nil {
		logger.Error("Failed to configure sandbox control plane", slog.String("error", err.Error()))
		os.Exit(1)
	}
	sandboxStore, err := sandboxcontrol.NewRedisStoreFromConfig(sandboxControlConfig)
	if err != nil {
		logger.Error("Failed to initialize sandbox provider state", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer sandboxStore.Close()
	baseSandboxRuntime, sandboxProviderName, err := sandboxruntime.NewFromEnv(
		ctx,
		builtinSandboxRuntime,
		sandboxStore.RedisClient(),
		envType,
		sandboxPolicy,
		workspaceLimits,
	)
	if err != nil {
		logger.Error("Failed to configure sandbox runtime", slog.String("error", err.Error()))
		os.Exit(1)
	}
	workspaceProvider, err := sandboxruntime.LoadWorkspaceProviderFromEnv()
	if err != nil {
		logger.Error("Failed to resolve sandbox workspace provider", slog.String("error", err.Error()))
		os.Exit(1)
	}
	sandboxRuntime, err := sandboxruntime.NewWorkspaceRuntimeForProvider(
		ctx,
		baseSandboxRuntime,
		workspaceProvider,
		workspaceConfig,
	)
	if err != nil {
		logger.Error("Failed to configure sandbox workspace provider", slog.String("error", err.Error()))
		os.Exit(1)
	}
	logger.Info("Sandbox runtime configured", slog.String("provider", sandboxProviderName))

	// Setup HTTP router
	router := setupRouter(cfg, logger)
	handler, err := api.NewHandler(backend, containerManager, logger, version, api.SandboxPolicy{
		TaskIdleTTL:      sandboxPolicy.TaskIdleTTL,
		MaxFileBytes:     workspaceConfig.MaxFileBytes,
		MCPIsolationTier: cfg.Container.DefaultIsolationTier,
	}, sandboxControlConfig, sandboxRuntime)
	if err != nil {
		logger.Error("Failed to initialize API handler", slog.String("error", err.Error()))
		os.Exit(1)
	}
	artifactRepository, err := artifactstore.NewFromConfig(ctx, artifactstore.ConfigFromWorkspace(workspaceConfig))
	if err != nil {
		logger.Error("Failed to configure sandbox artifact store", slog.String("error", err.Error()))
		os.Exit(1)
	}
	handler.SetSandboxArtifactStore(artifactRepository)
	handler.SetupRoutes(router)
	router.Any("/mcp/:instance_id/mcp", gin.WrapH(mcpGateway))
	router.DELETE("/mcp/:instance_id", gin.WrapF(mcpGateway.RetireHTTP))

	if features.IsEnabled(features.WarmPool) {
		if k8sBackend, ok := backend.(*backends.KubernetesBackend); ok {
			if wpClient := k8sBackend.GetWarmPoolClient(); wpClient != nil {
				if err := startSandboxTaskGC(ctx, logger, wpClient); err != nil {
					logger.Error("Failed to configure sandbox task GC", slog.String("error", err.Error()))
					os.Exit(1)
				}
			}
		}
	}

	// Run the sandbox execution consumer in-process (opt-in) so code execution
	// works without a standalone runner — used by docker-compose. Off by default
	// so Kubernetes, which runs a dedicated agentarea-sandbox-runner, keeps all
	// execution work out of the (more privileged) control plane.
	if err := startEmbeddedSandboxRunner(ctx, cfg, sandboxRuntime, sandboxProviderName, workspaceConfig, logger); err != nil {
		logger.Error("Failed to configure embedded sandbox runner", slog.String("error", err.Error()))
		os.Exit(1)
	}

	go mcpGateway.StartReaper(ctx)

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

// serveDataPlaneAndExit serves the data-plane API and never returns, unless the
// process was not asked to be a data plane — then it returns at once and the
// caller continues into control-plane wiring.
func serveDataPlaneAndExit(ctx context.Context, cfg *config.Config, backend backends.Backend, logger *slog.Logger) {
	if !dataplane.Enabled() {
		return
	}
	runDataplaneMode(ctx, cfg, backend, logger)
	os.Exit(0)
}

// runDataplaneMode serves the data-plane API and blocks until the process is signalled.
//
// It is reached only after the backend exists and before any control-plane
// dependency is constructed, so an agent host never holds database, Redis or
// secret-manager credentials — losing the host loses container control on that
// host and nothing more.
func runDataplaneMode(ctx context.Context, cfg *config.Config, backend backends.Backend, logger *slog.Logger) {
	dpCfg, err := dataplane.ConfigFromEnv()
	if err != nil {
		logger.Error("Refusing to start in data-plane mode", slog.String("error", err.Error()))
		os.Exit(1)
	}

	router := setupRouter(cfg, logger)
	dataplane.NewServer(dpCfg, backend, logger).Routes(router)

	// No WriteTimeout: proxied MCP traffic answers over SSE, and a write deadline
	// cuts a live stream mid-session rather than protecting anything. Slow
	// clients are bounded by ReadTimeout and by the request context instead.
	server := &http.Server{
		Addr:        dpCfg.ListenAddr,
		Handler:     router,
		ReadTimeout: 30 * time.Second,
	}

	go func() {
		logger.Info("MCP manager running as data plane",
			slog.String("agent_id", dpCfg.AgentID),
			slog.String("listen", dpCfg.ListenAddr),
		)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("Data-plane server failed", slog.String("error", err.Error()))
			os.Exit(1)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	select {
	case <-quit:
	case <-ctx.Done():
	}

	logger.Info("Shutting down data plane")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error("Data-plane shutdown failed", slog.String("error", err.Error()))
	}
	if err := backend.Shutdown(shutdownCtx); err != nil {
		logger.Error("Backend shutdown failed", slog.String("error", err.Error()))
	}
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

func startSandboxTaskGC(ctx context.Context, logger *slog.Logger, client *warmpool.Client) error {
	interval, err := getDurationEnv("SANDBOX_TASK_GC_INTERVAL", 30*time.Second)
	if err != nil {
		return err
	}
	if interval <= 0 {
		logger.Info("Sandbox task GC disabled")
		return nil
	}

	logger.Info("Starting sandbox task GC", slog.Duration("interval", interval))
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case now := <-ticker.C:
				deleted, err := client.DeleteExpiredTaskPods(ctx, now.UTC())
				if err != nil {
					logger.Warn("Sandbox task GC failed", slog.String("error", err.Error()))
					continue
				}
				if deleted > 0 {
					logger.Info("Sandbox task GC deleted expired pods", slog.Int("deleted", deleted))
				}
			}
		}
	}()
	return nil
}

// startEmbeddedSandboxRunner runs the sandbox execution consumer in-process,
// delegating actual execution to the backend's data plane (the docker
// sandbox-executor). This makes code execution work in docker-compose without a
// standalone sandbox-runner. Opt-in via SANDBOX_EMBEDDED_RUNNER=true; off by
// default so Kubernetes (which runs a dedicated agentarea-sandbox-runner) keeps
// execution work out of the more-privileged control plane.
func startEmbeddedSandboxRunner(ctx context.Context, cfg *config.Config, runtime sandboxruntime.Runtime, providerName string, workspaceConfig workspace.RepositoryConfig, logger *slog.Logger) error {
	rawEnabled := os.Getenv("SANDBOX_EMBEDDED_RUNNER")
	enabled := false
	if rawEnabled != "" {
		parsed, err := strconv.ParseBool(rawEnabled)
		if err != nil {
			return fmt.Errorf("SANDBOX_EMBEDDED_RUNNER must be a boolean: %w", err)
		}
		enabled = parsed
	}
	if !enabled {
		logger.Info("Embedded sandbox runner disabled (set SANDBOX_EMBEDDED_RUNNER=true to enable)")
		return nil
	}

	controlConfig, err := sandboxcontrol.LoadConfigFromEnv(cfg.Redis.URL)
	if err != nil {
		return fmt.Errorf("embedded sandbox runner control configuration: %w", err)
	}
	store, err := sandboxcontrol.NewRedisStoreFromConfig(controlConfig)
	if err != nil {
		return fmt.Errorf("embedded sandbox runner Redis store: %w", err)
	}

	placer, err := sandboxplacement.NewRegistry(sandboxplacement.Target{
		Executor: runtime,
		Capabilities: sandboxplacement.Capabilities{
			Name:   providerName,
			Region: os.Getenv("SANDBOX_REGION"),
		},
	})
	if err != nil {
		_ = store.Close()
		return fmt.Errorf("embedded sandbox runner placement: %w", err)
	}

	workspaceRepository, err := workspace.NewRepositoryFromConfig(ctx, workspaceConfig)
	if err != nil {
		_ = store.Close()
		return fmt.Errorf("embedded sandbox runner workspace repository: %w", err)
	}
	runner := sandboxrunner.NewWithPlacerAndWorkspaceRepository(
		sandboxrunner.ConfigFromEnv(), store, placer, logger, workspaceRepository,
	)
	go func() {
		if err := runner.Run(ctx); err != nil && err != context.Canceled {
			logger.Error("Embedded sandbox runner stopped", slog.String("error", err.Error()))
		}
	}()
	logger.Info("Embedded sandbox runner started",
		slog.String("sandbox_target", providerName),
		slog.String("sandbox_region", os.Getenv("SANDBOX_REGION")))
	return nil
}

func getDurationEnv(name string, fallback time.Duration) (time.Duration, error) {
	value := os.Getenv(name)
	if value == "" {
		return fallback, nil
	}
	duration, err := time.ParseDuration(value)
	if err != nil {
		return 0, fmt.Errorf("%s must be a duration: %w", name, err)
	}
	return duration, nil
}
