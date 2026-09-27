// Package runnerapp is the standalone sandbox runner's startup, shared by every
// distribution of the binary.
package runnerapp

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"strings"

	"github.com/go-redis/redis/v8"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
	"github.com/agentarea/mcp-manager/internal/sandboxplacement"
	"github.com/agentarea/mcp-manager/internal/sandboxrunner"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

// Configure runs after the base sandbox runtime is created and before the
// workspace decorator wraps it. It receives the runner's own Redis client; the
// runner never holds a database connection.
type Configure func(context.Context, *config.Config, *slog.Logger, *redis.Client, sandboxruntime.ManagedRuntime) error

// Run serves sandbox execution until ctx ends. configure may be nil.
func Run(ctx context.Context, cfg *config.Config, logger *slog.Logger, configure Configure) error {
	controlPolicy, err := sandboxruntime.LoadControlPolicyFromEnv()
	if err != nil {
		return failed(logger, "failed to configure sandbox control policy", err)
	}
	workspaceConfig, err := workspace.LoadConfigFromEnv()
	if err != nil {
		return failed(logger, "failed to configure sandbox workspace policy", err)
	}
	workspaceLimits := sandboxruntime.WorkspaceLimits{
		MaxFiles: workspaceConfig.MaxFiles, MaxFileBytes: workspaceConfig.MaxFileBytes, MaxBytes: workspaceConfig.MaxBytes,
	}

	controlConfig, err := sandboxcontrol.LoadConfigFromEnv(cfg.Redis.URL)
	if err != nil {
		return failed(logger, "failed to configure sandbox control plane", err)
	}
	store, err := sandboxcontrol.NewRedisStoreFromConfig(controlConfig)
	if err != nil {
		return failed(logger, "failed to initialize sandbox execution store", err)
	}
	defer store.Close()

	var builtinRuntime sandboxruntime.ManagedRuntime
	configuredProvider := strings.ToLower(strings.TrimSpace(os.Getenv("SANDBOX_PROVIDER")))
	if configuredProvider == "" || configuredProvider == "kubernetes" || configuredProvider == "agentarea" {
		backend, err := backends.NewKubernetesBackend(cfg, logger, controlPolicy.TaskLeaseTTL)
		if err != nil {
			return failed(logger, "failed to initialize kubernetes backend", err)
		}
		if err := backend.Initialize(ctx); err != nil {
			return failed(logger, "failed to initialize kubernetes backend resources", err)
		}
		defer func() { _ = backend.Shutdown(context.Background()) }()
		builtinRuntime = backend
	}

	runtime, providerName, err := sandboxruntime.NewFromEnv(ctx, builtinRuntime, store.RedisClient(), "kubernetes", controlPolicy, workspaceLimits)
	if err != nil {
		return failed(logger, "failed to configure sandbox runtime", err)
	}
	if configure != nil {
		if err := configure(ctx, cfg, logger, store.RedisClient(), runtime); err != nil {
			return failed(logger, "failed to configure sandbox runtime extension", err)
		}
	}
	workspaceProvider, err := sandboxruntime.LoadWorkspaceProviderFromEnv()
	if err != nil {
		return failed(logger, "failed to resolve sandbox workspace provider", err)
	}
	composed, err := sandboxruntime.NewWorkspaceRuntimeForProvider(ctx, runtime, workspaceProvider, workspaceConfig)
	if err != nil {
		return failed(logger, "failed to configure sandbox workspace runtime", err)
	}
	placer, err := sandboxplacement.NewRegistry(sandboxplacement.Target{
		Executor: composed,
		Capabilities: sandboxplacement.Capabilities{
			Name:   providerName,
			Region: os.Getenv("SANDBOX_REGION"),
		},
	})
	if err != nil {
		return failed(logger, "failed to build sandbox placement registry", err)
	}

	workspaceRepository, err := workspace.NewRepositoryFromConfig(ctx, workspaceConfig)
	if err != nil {
		return failed(logger, "failed to configure sandbox output repository", err)
	}
	runner := sandboxrunner.NewWithPlacerAndWorkspaceRepository(
		sandboxrunner.ConfigFromEnv(), store, placer, logger, workspaceRepository,
	)
	if err := runner.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
		return failed(logger, "sandbox runner stopped", err)
	}
	logger.Info("sandbox runner shutdown complete")
	return nil
}

func failed(logger *slog.Logger, message string, err error) error {
	logger.Error(message, slog.String("error", err.Error()))
	return fmt.Errorf("%s: %w", message, err)
}

// NewLogger configures the runner's structured logging.
func NewLogger(cfg *config.Config) *slog.Logger {
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
