package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
	"github.com/agentarea/mcp-manager/internal/sandboxplacement"
	"github.com/agentarea/mcp-manager/internal/sandboxrunner"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

func main() {
	cfg := config.Load()
	logger := setupLogging(cfg)

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	controlPolicy, err := sandboxruntime.LoadControlPolicyFromEnv()
	if err != nil {
		logger.Error("failed to configure sandbox control policy", slog.String("error", err.Error()))
		os.Exit(1)
	}
	workspaceConfig, err := workspace.LoadConfigFromEnv()
	if err != nil {
		logger.Error("failed to configure sandbox workspace policy", slog.String("error", err.Error()))
		os.Exit(1)
	}
	workspaceLimits := sandboxruntime.WorkspaceLimits{
		MaxFiles: workspaceConfig.MaxFiles, MaxFileBytes: workspaceConfig.MaxFileBytes, MaxBytes: workspaceConfig.MaxBytes,
	}

	controlConfig, err := sandboxcontrol.LoadConfigFromEnv(cfg.Redis.URL)
	if err != nil {
		logger.Error("failed to configure sandbox control plane", slog.String("error", err.Error()))
		os.Exit(1)
	}
	store, err := sandboxcontrol.NewRedisStoreFromConfig(controlConfig)
	if err != nil {
		logger.Error("failed to initialize sandbox execution store", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer store.Close()

	var builtinRuntime sandboxruntime.ManagedRuntime
	var backend *backends.KubernetesBackend
	configuredProvider := strings.ToLower(strings.TrimSpace(os.Getenv("SANDBOX_PROVIDER")))
	if configuredProvider == "" || configuredProvider == "kubernetes" || configuredProvider == "agentarea" {
		backend, err = backends.NewKubernetesBackend(cfg, logger, controlPolicy.TaskLeaseTTL)
		if err != nil {
			logger.Error("failed to initialize kubernetes backend", slog.String("error", err.Error()))
			os.Exit(1)
		}
		if err := backend.Initialize(ctx); err != nil {
			logger.Error("failed to initialize kubernetes backend resources", slog.String("error", err.Error()))
			os.Exit(1)
		}
		defer func() { _ = backend.Shutdown(context.Background()) }()
		builtinRuntime = backend
	}

	runtime, providerName, err := sandboxruntime.NewFromEnv(ctx, builtinRuntime, store.RedisClient(), "kubernetes", controlPolicy, workspaceLimits)
	if err != nil {
		logger.Error("failed to configure sandbox runtime", slog.String("error", err.Error()))
		os.Exit(1)
	}
	workspaceProvider, err := sandboxruntime.LoadWorkspaceProviderFromEnv()
	if err != nil {
		logger.Error("failed to resolve sandbox workspace provider", slog.String("error", err.Error()))
		os.Exit(1)
	}
	runtime, err = sandboxruntime.NewWorkspaceRuntimeForProvider(ctx, runtime, workspaceProvider, workspaceConfig)
	if err != nil {
		logger.Error("failed to configure sandbox workspace runtime", slog.String("error", err.Error()))
		os.Exit(1)
	}
	placer, err := sandboxplacement.NewRegistry(sandboxplacement.Target{
		Executor: runtime,
		Capabilities: sandboxplacement.Capabilities{
			Name:   providerName,
			Region: os.Getenv("SANDBOX_REGION"),
		},
	})
	if err != nil {
		logger.Error("failed to build sandbox placement registry", slog.String("error", err.Error()))
		os.Exit(1)
	}

	workspaceRepository, err := workspace.NewRepositoryFromConfig(ctx, workspaceConfig)
	if err != nil {
		logger.Error("failed to configure sandbox output repository", slog.String("error", err.Error()))
		os.Exit(1)
	}
	runner := sandboxrunner.NewWithPlacerAndWorkspaceRepository(
		sandboxrunner.ConfigFromEnv(), store, placer, logger, workspaceRepository,
	)
	if err := runner.Run(ctx); err != nil && err != context.Canceled {
		logger.Error("sandbox runner stopped", slog.String("error", err.Error()))
		os.Exit(1)
	}
	logger.Info("sandbox runner shutdown complete")
}

func setupLogging(cfg *config.Config) *slog.Logger {
	opts := &slog.HandlerOptions{Level: logLevel(cfg.Logging.Level)}
	if cfg.Logging.Format == "text" {
		return slog.New(slog.NewTextHandler(os.Stdout, opts))
	}
	return slog.New(slog.NewJSONHandler(os.Stdout, opts))
}

func logLevel(level string) slog.Level {
	switch strings.ToUpper(level) {
	case "DEBUG":
		return slog.LevelDebug
	case "WARN", "WARNING":
		return slog.LevelWarn
	case "ERROR":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}
