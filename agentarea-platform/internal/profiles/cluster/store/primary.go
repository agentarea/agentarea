// Package store opens the profile's own connection to the primary for the
// adapters that take a db.Querier rather than a workspace session (the
// authentication store reads API keys and workspaces of every workspace).
package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// PrimaryPoolSize bounds the profile's primary connections.
const PrimaryPoolSize = 5

// Primary is a small pool on the primary.
type Primary struct {
	pool *pgxpool.Pool
}

// OpenPrimary connects to c's primary; it does not wait for a connection.
func OpenPrimary(ctx context.Context, c db.Config) (*Primary, error) {
	pc, err := pgxpool.ParseConfig(c.WriteURL())
	if err != nil {
		return nil, fmt.Errorf("primary pool: %w", err)
	}
	pc.MaxConns = PrimaryPoolSize
	if c.PoolRecycle > 0 {
		pc.MaxConnLifetime = c.PoolRecycle
	}
	pool, err := pgxpool.NewWithConfig(ctx, pc)
	if err != nil {
		return nil, fmt.Errorf("primary pool: %w", err)
	}
	return &Primary{pool: pool}, nil
}

// Querier runs statements on the primary, outside any transaction.
func (p *Primary) Querier() db.Querier { return p.pool }

// Close closes the pool.
func (p *Primary) Close() { p.pool.Close() }
