package container

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"time"

	"github.com/agentarea/mcp-manager/internal/database"
)

// idleReaperSQL selects lazily-provisioned instances that have gone quiet.
//
// Only lazy instances are eligible: an instance provisioned eagerly was asked
// to stay up, and stopping it would be a behaviour change rather than a
// reclamation. NULL last_used_at is deliberately NOT idle — it means no call has
// been observed through the proxy yet (including every row predating that
// column), and treating "unknown" as "idle" would stop instances that are
// simply new.
const idleReaperSQL = `
SELECT id::text, name
FROM mcp_server_instances
WHERE status = 'running'
  AND COALESCE((json_spec->>'lazy_provisioning')::boolean, false) = true
  AND last_used_at IS NOT NULL
  AND last_used_at < now() - make_interval(secs => $1)
`

// runIdleReaper owns the reaper's database handle for the process lifetime.
//
// It opens its own connection rather than sharing the short-lived ones the
// startup paths use, because this loop outlives them. A missing database
// configuration disables reaping instead of failing startup: the manager's
// other work does not depend on it.
func (m *Manager) runIdleReaper(ctx context.Context) {
	if m.config.Container.MCPIdleTimeout <= 0 {
		m.logger.Info("MCP idle reaper disabled (MCP_IDLE_TIMEOUT unset)")
		return
	}

	connStr := database.BuildConnStr(m.logger)
	if connStr == "" {
		m.logger.Warn("MCP idle reaper not started: database credentials not configured")
		return
	}

	db, err := sql.Open("pgx", connStr)
	if err != nil {
		m.logger.Warn("MCP idle reaper not started", slog.String("error", err.Error()))
		return
	}
	defer db.Close()

	m.StartIdleReaper(
		ctx,
		db,
		m.config.Container.MCPIdleTimeout,
		m.config.Container.MCPIdleSweepInterval,
	)
}

// StartIdleReaper sweeps for idle instances until ctx is cancelled.
//
// Runs in the control plane rather than beside the containers so one sweeper
// covers every data plane, matching how the sandbox runner already owns its
// pods' idleness.
func (m *Manager) StartIdleReaper(ctx context.Context, db *sql.DB, idleTimeout, interval time.Duration) {
	if idleTimeout <= 0 {
		m.logger.Info("MCP idle reaper disabled (no idle timeout configured)")
		return
	}

	m.logger.Info("Starting MCP idle reaper",
		slog.Duration("idle_timeout", idleTimeout),
		slog.Duration("interval", interval))

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			m.logger.Info("MCP idle reaper stopped")
			return
		case <-ticker.C:
			stopped, err := m.ReapIdleInstances(ctx, db, idleTimeout)
			if err != nil {
				// A failed sweep is not fatal: the next tick retries, and the
				// worst case is instances staying up longer than intended.
				m.logger.Warn("MCP idle sweep failed", slog.String("error", err.Error()))
				continue
			}
			if stopped > 0 {
				m.logger.Info("Reaped idle MCP instances", slog.Int("stopped", stopped))
			}
		}
	}
}

// ReapIdleInstances stops containers for lazily-provisioned MCP instances that
// have not been called for longer than idleTimeout.
//
// This is the half of serverless that was missing: lazy provisioning starts an
// instance on demand, but nothing ever stopped it, so instances accumulated and
// ran indefinitely. Stopping only the container — never the database row — is
// what makes it reversible: the next proxied call provisions it again through
// the same path that started it the first time.
func (m *Manager) ReapIdleInstances(ctx context.Context, db *sql.DB, idleTimeout time.Duration) (int, error) {
	if idleTimeout <= 0 {
		return 0, nil
	}

	rows, err := db.QueryContext(ctx, idleReaperSQL, idleTimeout.Seconds())
	if err != nil {
		return 0, fmt.Errorf("querying idle mcp instances: %w", err)
	}
	defer rows.Close()

	type idleInstance struct {
		id   string
		name string
	}
	var idle []idleInstance
	for rows.Next() {
		var inst idleInstance
		if err := rows.Scan(&inst.id, &inst.name); err != nil {
			m.logger.Warn("Failed to scan idle instance row", slog.String("error", err.Error()))
			continue
		}
		idle = append(idle, inst)
	}
	if err := rows.Err(); err != nil {
		return 0, fmt.Errorf("iterating idle mcp instances: %w", err)
	}

	stopped := 0
	for _, inst := range idle {
		// The instance row survives — only the container goes — so the next
		// proxied call provisions it again through the path that started it
		// the first time. `name` is the service name the manager keys on, the
		// same mapping the DB-driven auto-restart uses.
		//
		// A container that is already gone is the desired end state, so a
		// failure is logged and skipped rather than aborting the sweep: one
		// stuck instance must not keep every other one running.
		if err := m.DeleteContainer(ctx, inst.name); err != nil {
			m.logger.Warn("Failed to stop idle MCP instance",
				slog.String("instance_id", inst.id),
				slog.String("error", err.Error()))
			continue
		}
		stopped++
		m.logger.Info("Stopped idle MCP instance",
			slog.String("instance_id", inst.id),
			slog.Duration("idle_timeout", idleTimeout))
	}

	return stopped, nil
}
