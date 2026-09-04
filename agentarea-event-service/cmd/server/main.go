package main

import (
	"context"
	"database/sql"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	_ "github.com/lib/pq"
	"github.com/redis/go-redis/v9"

	"github.com/agentarea/event-service/internal/broker"
	"github.com/agentarea/event-service/internal/channels"
	"github.com/agentarea/event-service/internal/channels/telegram"
	"github.com/agentarea/event-service/internal/claim"
	"github.com/agentarea/event-service/internal/config"
	"github.com/agentarea/event-service/internal/polling"
	"github.com/agentarea/event-service/internal/submit"
)

const version = "0.0.14"

func main() {
	// Structured logging
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})))

	cfg := config.Load()

	slog.Info("event-service starting",
		"version", version,
		"worker_id", cfg.WorkerID,
		"inbound_stream", cfg.InboundStream,
		"enable_telegram_polling", cfg.EnableTelegramPolling,
		"poll_interval", cfg.PollInterval,
		"max_pollers", cfg.MaxPollers,
		"port", cfg.Port,
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

	// Register dev-only polling channel adapters.
	if cfg.EnableTelegramPolling {
		channels.Register("telegram_polling", telegram.NewPoller)
		slog.Info("telegram getUpdates polling enabled")
	} else {
		slog.Info("telegram getUpdates polling disabled")
	}

	// Build dependencies
	streamBroker := broker.NewRedisStreams(redisClient)
	submitter := submit.NewStreamSubmitter(streamBroker, cfg.InboundStream)
	claimer := claim.NewRedisClaimer(redisClient, cfg.WorkerID)

	mgr := polling.NewManager(db, submitter, claimer, cfg.PollInterval, cfg.MaxPollers)

	// Run polling manager (outbound delivery handled by Python worker)
	errCh := make(chan error, 1)

	healthServer := newHealthServer(cfg.Port)
	go func() {
		slog.Info("starting health server", "addr", healthServer.Addr)
		if err := healthServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			errCh <- err
		}
	}()

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

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutdownCancel()
	if err := healthServer.Shutdown(shutdownCtx); err != nil {
		slog.Warn("health server shutdown failed", "error", err)
	}

	slog.Info("event-service stopped")
}

func newHealthServer(port string) *http.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	return &http.Server{
		Addr:              ":" + port,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
}
