package mcpidle

import (
	"context"
	"database/sql"
	"log/slog"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/database"

	// This package is the one calling sql.Open("pgx", ...), so it registers the
	// driver itself rather than relying on another package happening to be
	// linked into the same binary.
	_ "github.com/jackc/pgx/v5/stdlib"
)

// Run owns the reaper's database handle for the process lifetime.
//
// It opens its own connection rather than sharing the short-lived ones the
// startup paths use, because this loop outlives them. A missing database
// configuration disables reaping instead of failing startup: the manager's
// other work does not depend on it.
func Run(ctx context.Context, cfg *config.Config, backend backends.Backend, logger *slog.Logger) {
	if cfg.Container.MCPIdleTimeout <= 0 {
		logger.Info("MCP idle reaper disabled (MCP_IDLE_TIMEOUT unset)")
		return
	}

	connStr := database.BuildConnStr(logger)
	if connStr == "" {
		logger.Warn("MCP idle reaper not started: database credentials not configured")
		return
	}

	db, err := sql.Open("pgx", connStr)
	if err != nil {
		logger.Warn("MCP idle reaper not started", slog.String("error", err.Error()))
		return
	}
	defer db.Close()

	New(backend, logger).Start(
		ctx,
		db,
		cfg.Container.MCPIdleTimeout,
		cfg.Container.MCPIdleSweepInterval,
	)
}
