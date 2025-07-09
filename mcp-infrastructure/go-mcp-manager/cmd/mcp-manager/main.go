package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/api"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/container"
	"github.com/agentarea/mcp-manager/internal/events"
	"github.com/agentarea/mcp-manager/internal/providers"
	"github.com/agentarea/mcp-manager/internal/secrets"
)

const version = "0.1.0"

func main() {
	// Load configuration
	cfg := config.Load()

	// Setup logging
	logger := setupLogging(cfg)

	// Create context for graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Initialize components
	containerManager := container.NewManager(cfg, logger)

	// Initialize container manager
	if err := containerManager.Initialize(ctx); err != nil {
		logger.Error("Failed to initialize container manager", slog.String("error", err.Error()))
		os.Exit(1)
	}

	// Start Traefik in background
	go func() {
		if err := startTraefik(logger); err != nil {
			logger.Error("Failed to start Traefik", slog.String("error", err.Error()))
		}
	}()

	// Initialize secret resolver with Infisical SDK
	secretResolver, err := secrets.NewSecretResolver(logger)
	if err != nil {
		logger.Error("Failed to initialize secret resolver", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer secretResolver.Close()

	dockerProvider := providers.NewDockerProvider(secretResolver, containerManager, logger)
	urlProvider := providers.NewURLProvider(logger)
	providerManager := providers.NewProviderManager(dockerProvider, urlProvider)

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
	handler := api.NewHandler(containerManager, version)
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
		logger.Info("Starting MCP Manager with embedded Traefik",
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

	// Shutdown container manager
	if err := containerManager.Shutdown(shutdownCtx); err != nil {
		logger.Error("Failed to shutdown container manager", slog.String("error", err.Error()))
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

// startTraefik starts the Traefik reverse proxy
func startTraefik(logger *slog.Logger) error {
	logger.Info("Starting embedded Traefik reverse proxy")

	// Create Traefik static configuration
	if err := createTraefikStaticConfig(); err != nil {
		return fmt.Errorf("failed to create Traefik static config: %w", err)
	}

	// Ensure dynamic config directory exists
	os.MkdirAll("/etc/traefik", 0755)

	// Start Traefik process
	cmd := exec.Command("traefik", "--configfile=/etc/traefik/traefik.yml")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start Traefik: %w", err)
	}

	logger.Info("Traefik started successfully", slog.Int("pid", cmd.Process.Pid))

	// Wait for process to finish (this will run until container stops)
	if err := cmd.Wait(); err != nil {
		logger.Error("Traefik process exited", slog.String("error", err.Error()))
		return err
	}

	return nil
}

// createTraefikStaticConfig creates the static Traefik configuration
func createTraefikStaticConfig() error {
	staticConfig := `
# Static Traefik configuration
global:
  checkNewVersion: false
  sendAnonymousUsage: false

log:
  level: INFO

entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"

providers:
  file:
    directory: /etc/traefik
    watch: true

api:
  dashboard: true
  insecure: true
`

	return os.WriteFile("/etc/traefik/traefik.yml", []byte(staticConfig), 0644)
}
