package main

import (
	"context"
	"database/sql"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	_ "github.com/lib/pq"
	"github.com/redis/go-redis/v9"

	"github.com/agentarea/event-service/internal/channels"
	"github.com/agentarea/event-service/internal/channels/telegram"
	"github.com/agentarea/event-service/internal/claim"
	"github.com/agentarea/event-service/internal/config"
	"github.com/agentarea/event-service/internal/polling"
	"github.com/agentarea/event-service/internal/submit"
)

func main() {
	// Structured logging
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})))

	cfg := config.Load()

	slog.Info("event-service starting",
		"worker_id", cfg.WorkerID,
		"poll_interval", cfg.PollInterval,
		"max_pollers", cfg.MaxPollers,
	)

	// Connect to PostgreSQL
	db, err := sql.Open("postgres", cfg.DatabaseURL)
	if err != nil {
		slog.Error("failed to open database", "error", err)
		os.Exit(1)
	}
	defer db.Close()

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	if err := db.PingContext(ctx); err != nil {
		slog.Error("failed to ping database", "error", err)
		os.Exit(1)
	}
	slog.Info("database connected")

	// Connect to Redis
	opts, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		slog.Error("failed to parse redis URL", "error", err)
		os.Exit(1)
	}
	redisClient := redis.NewClient(opts)
	defer redisClient.Close()

	if err := redisClient.Ping(ctx).Err(); err != nil {
		slog.Error("failed to ping redis", "error", err)
		os.Exit(1)
	}
	slog.Info("redis connected")

	// Register channel pollers
	channels.Register("telegram_polling", telegram.NewPoller)

	// Build dependencies
	submitter := submit.NewRedisSubmitter(redisClient)
	claimer := claim.NewRedisClaimer(redisClient, cfg.WorkerID)

	mgr := polling.NewManager(db, submitter, claimer, cfg.PollInterval, cfg.MaxPollers)

	// Run polling manager (outbound delivery handled by Python worker)
	errCh := make(chan error, 1)

	go func() {
		slog.Info("starting polling manager")
		errCh <- mgr.Run(ctx)
	}()

	// Wait for first error or shutdown
	if err := <-errCh; err != nil && err != context.Canceled {
		slog.Error("service exited with error", "error", err)
		cancel()
		os.Exit(1)
	}

	slog.Info("event-service stopped")
}
