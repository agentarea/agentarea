// Package mcpidle stops lazily-provisioned MCP instances that have gone unused.
//
// It sits above the backends rather than inside one: an MCP instance is a
// container on docker and a Deployment on Kubernetes, but its idleness is the
// same fact in the same table either way. Owning the sweep here is what keeps
// the two data planes on one lifecycle instead of two that drift apart.
package mcpidle

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
)

// reaperSQL selects lazily-provisioned instances that have gone quiet.
//
// "Provisioned" is verification->>'status' = 'succeeded'. That is the same fact
// the tool-call path checks before dispatching, so the reaper and the caller
// agree on what "up" means. (mcp_server_instances has no status column — it was
// dropped when the verification object replaced it.)
//
// Only lazy instances are eligible: an instance provisioned eagerly was asked
// to stay up, and stopping it would be a behaviour change rather than a
// reclamation. NULL last_used_at is deliberately NOT idle — it means no call has
// been observed through the proxy yet (including every row predating that
// column), and treating "unknown" as "idle" would stop instances that are
// simply new.
const reaperSQL = `
SELECT id::text, name
FROM mcp_server_instances
WHERE COALESCE((json_spec->>'lazy_provisioning')::boolean, false) = true
  AND (verification->>'status') = 'succeeded'
  AND last_used_at IS NOT NULL
  AND last_used_at < now() - make_interval(secs => $1)
`

// releaseSQL records that the instance is no longer provisioned.
//
// Without this the row keeps claiming 'succeeded' after its workload is gone,
// and the next tool call skips lazy provisioning entirely — it dispatches to an
// endpoint that no longer exists and fails. Resetting to 'never_attempted' is
// what makes the instance come back on demand instead of needing a manual
// re-verify, and it also drops the row out of reaperSQL so a stopped instance
// is not swept again every tick.
//
// The 'succeeded' guard makes this a compare-and-set: if a verification started
// between the select and here, its state wins rather than being clobbered.
// Lazy rows are excluded from the platform's re-verify sweep, so this does not
// hand the instance to a background verifier — only to its next caller.
const releaseSQL = `
UPDATE mcp_server_instances
SET verification = '{"schema_version":1,"status":"never_attempted","at":null,"error":null}'::jsonb
WHERE id = $1::uuid
  AND (verification->>'status') = 'succeeded'
`

// idleInstance is one instance the sweep decided to stop.
type idleInstance struct {
	id   string
	name string
}

// Reaper sweeps idle MCP instances off whichever backend is in use.
type Reaper struct {
	backend backends.Backend
	logger  *slog.Logger
}

func New(backend backends.Backend, logger *slog.Logger) *Reaper {
	return &Reaper{backend: backend, logger: logger}
}

// Start sweeps for idle instances until ctx is cancelled.
func (r *Reaper) Start(ctx context.Context, db *sql.DB, idleTimeout, interval time.Duration) {
	if idleTimeout <= 0 {
		r.logger.Info("MCP idle reaper disabled (no idle timeout configured)")
		return
	}
	if interval <= 0 {
		r.logger.Warn("MCP idle reaper not started: sweep interval must be positive",
			slog.Duration("interval", interval))
		return
	}

	r.logger.Info("Starting MCP idle reaper",
		slog.Duration("idle_timeout", idleTimeout),
		slog.Duration("interval", interval))

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			r.logger.Info("MCP idle reaper stopped")
			return
		case <-ticker.C:
			stopped, err := r.Reap(ctx, db, idleTimeout)
			if err != nil {
				// A failed sweep is not fatal: the next tick retries, and the
				// worst case is instances staying up longer than intended.
				r.logger.Warn("MCP idle sweep failed", slog.String("error", err.Error()))
				continue
			}
			if stopped > 0 {
				r.logger.Info("Reaped idle MCP instances", slog.Int("stopped", stopped))
			}
		}
	}
}

// Reap stops the instances that have not been called for longer than idleTimeout.
//
// This is the half of serverless that was missing: lazy provisioning starts an
// instance on demand, but nothing ever stopped it, so instances accumulated and
// ran indefinitely. Only the workload goes — never the database row — which is
// what makes it reversible: the next proxied call provisions it again through
// the same path that started it the first time.
func (r *Reaper) Reap(ctx context.Context, db *sql.DB, idleTimeout time.Duration) (int, error) {
	if idleTimeout <= 0 {
		return 0, nil
	}

	// One sweeper at a time across every manager replica. Without this, two
	// replicas select the same rows and race to delete the same workloads.
	lock, acquired, err := acquireSweepLock(ctx, db, r.logger)
	if err != nil {
		return 0, err
	}
	if !acquired {
		r.logger.Debug("Skipping MCP idle sweep: another replica holds the sweep lock")
		return 0, nil
	}
	defer lock.release(ctx)

	idle, err := r.findIdle(ctx, db, idleTimeout)
	if err != nil {
		return 0, err
	}

	release := func(ctx context.Context, id string) error {
		_, err := db.ExecContext(ctx, releaseSQL, id)
		return err
	}

	return r.stop(ctx, idle, idleTimeout, release), nil
}

// findIdle runs the selection query. Kept apart from stop() so the decision of
// *which* instances go and the decision of *how* they are addressed can be
// reasoned about — and tested — separately.
func (r *Reaper) findIdle(ctx context.Context, db *sql.DB, idleTimeout time.Duration) ([]idleInstance, error) {
	rows, err := db.QueryContext(ctx, reaperSQL, idleTimeout.Seconds())
	if err != nil {
		return nil, fmt.Errorf("querying idle mcp instances: %w", err)
	}
	defer rows.Close()

	var idle []idleInstance
	for rows.Next() {
		var inst idleInstance
		if err := rows.Scan(&inst.id, &inst.name); err != nil {
			r.logger.Warn("Failed to scan idle instance row", slog.String("error", err.Error()))
			continue
		}
		idle = append(idle, inst)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterating idle mcp instances: %w", err)
	}

	return idle, nil
}

func (r *Reaper) stop(
	ctx context.Context,
	idle []idleInstance,
	idleTimeout time.Duration,
	release func(context.Context, string) error,
) int {
	stopped := 0
	for _, inst := range idle {
		// Address the workload by instance id, not by the instance's name. Both
		// backends stamp the id onto what they create (docker: MCP_INSTANCE_ID
		// in the container env and the service name; Kubernetes: the
		// agentarea.io/instance-id annotation and the configmap), and both
		// DeleteInstance implementations resolve through exactly those. The
		// display name is not a lookup key on either.
		//
		// A failure is logged and skipped rather than aborting the sweep: one
		// stuck instance must not keep every other one running. The row is left
		// claiming 'succeeded' so the next tick retries the delete — better a
		// repeated warning than a row that says "gone" while its workload runs.
		if err := r.backend.DeleteInstance(ctx, inst.id); err != nil {
			r.logger.Warn("Failed to stop idle MCP instance",
				slog.String("instance_id", inst.id),
				slog.String("instance_name", inst.name),
				slog.String("error", err.Error()))
			continue
		}

		// Only now is the instance really unprovisioned. If this write fails the
		// workload is already gone while the row still claims 'succeeded', so
		// the next call would dispatch into nothing — log it loudly rather than
		// counting the instance as cleanly reclaimed.
		if err := release(ctx, inst.id); err != nil {
			r.logger.Error("Stopped idle MCP instance but failed to release its state; the next call to it will fail until it is re-verified",
				slog.String("instance_id", inst.id),
				slog.String("instance_name", inst.name),
				slog.String("error", err.Error()))
			continue
		}

		stopped++
		r.logger.Info("Stopped idle MCP instance",
			slog.String("instance_id", inst.id),
			slog.String("instance_name", inst.name),
			slog.Duration("idle_timeout", idleTimeout))
	}

	return stopped
}
