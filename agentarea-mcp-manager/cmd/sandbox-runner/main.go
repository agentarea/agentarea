package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
	"github.com/agentarea/mcp-manager/internal/sandboxrunner"
)

func main() {
	cfg := config.Load()
	logger := setupLogging(cfg)

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	store, err := sandboxcontrol.NewRedisStore(
		cfg.Redis.URL,
		os.Getenv("SANDBOX_CONTROL_REDIS_PREFIX"),
		durationEnv("SANDBOX_EXECUTION_RECORD_TTL", 24*time.Hour),
	)
	if err != nil {
		logger.Error("failed to initialize sandbox execution store", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer store.Close()

	backend, err := backends.NewKubernetesBackend(cfg, logger)
	if err != nil {
		logger.Error("failed to initialize kubernetes backend", slog.String("error", err.Error()))
		os.Exit(1)
	}
	if err := backend.Initialize(ctx); err != nil {
		logger.Error("failed to initialize kubernetes backend resources", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer func() { _ = backend.Shutdown(context.Background()) }()

	runner := sandboxrunner.New(sandboxrunner.ConfigFromEnv(), store, backend, logger)
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

func durationEnv(name string, fallback time.Duration) time.Duration {
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
