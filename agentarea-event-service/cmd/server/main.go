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
	"github.com/agentarea/event-service/internal/claim"
	"github.com/agentarea/event-service/internal/config"
	"github.com/agentarea/event-service/internal/egress"
	"github.com/agentarea/event-service/internal/ingest"
	"github.com/agentarea/event-service/internal/mcpevents"
	"github.com/agentarea/event-service/internal/polling"
	"github.com/agentarea/event-service/internal/secrets"
	"github.com/agentarea/event-service/internal/source"
	"github.com/agentarea/event-service/internal/tracing"
	"github.com/agentarea/event-service/internal/transport"
)

const version = "0.1.2"

func main() {
	// Structured logging
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})))

	cfg, err := config.Load()
	if err != nil {
		slog.Error("invalid configuration", "error", err)
		os.Exit(1)
	}

	slog.Info("event-service starting",
		"version", version,
		"worker_id", cfg.WorkerID,
		"poll_interval", cfg.PollInterval,
		"max_pollers", cfg.MaxPollers,
		"port", cfg.Port,
		"otel_enabled", cfg.OTelEnabled,
	)

	if cfg.DatabaseURL == "" {
		slog.Error("database is not configured: set AGENTAREA_DB_HOST, AGENTAREA_DB_NAME, AGENTAREA_DB_USER and AGENTAREA_DB_PASSWORD")
		os.Exit(1)
	}

	// Connect to PostgreSQL
	db, err := sql.Open("postgres", cfg.DatabaseURL)
	if err != nil {
		slog.Error("failed to open database", "error", err)
		os.Exit(1)
	}
	defer db.Close()

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	shutdownTracing, err := tracing.Setup(ctx, cfg.OTelEnabled)
	if err != nil {
		slog.Error("failed to set up tracing", "error", err)
		os.Exit(1)
	}
	defer func() {
		flushCtx, flushCancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer flushCancel()
		if err := shutdownTracing(flushCtx); err != nil {
			slog.Error("tracing shutdown failed", "error", err)
		}
	}()

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

	fernet, err := secrets.NewFernet(cfg.SecretKey)
	if err != nil {
		slog.Error("invalid AGENTAREA_SECRET_ENCRYPTION_KEY", "error", err)
		os.Exit(1)
	}
	policy, err := egress.NewPolicy(cfg.Egress.AllowPrivate, cfg.Egress.PrivateAllowlist)
	if err != nil {
		slog.Error("invalid AGENTAREA_HTTP_PRIVATE_ALLOWLIST", "error", err)
		os.Exit(1)
	}

	// Go fetches and publishes raw items to streams.ingest; the platform's
	// ingest names, keys and dedups them.
	mcp := mcpevents.NewClient(cfg.MCPManagerURL, cfg.MCPGatewaySecret)
	mgr := polling.NewManager(polling.Deps{
		Sources:    source.NewStore(db),
		Secrets:    secrets.NewStore(db, fernet),
		Transports: transport.NewSet(policy, mcp),
		Publisher:  ingest.NewPublisher(broker.NewRedisStreams(redisClient, cfg.Namespace)),
		Caller:     transport.NewCaller(policy),
		MCP:        mcp,
		Claimer:    claim.NewRedisClaimer(redisClient, cfg.WorkerID),
		APIURL:     cfg.APIURL,
		Interval:   cfg.PollInterval,
		MaxPollers: cfg.MaxPollers,
	})

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
