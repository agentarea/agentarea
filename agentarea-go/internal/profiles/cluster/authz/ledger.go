package authz

import (
	"context"

	kauthz "github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// Ledger is the graph_migrations table (id text primary key, applied_at
// timestamptz), the one Python's `migrate` records into.
type Ledger struct {
	Global db.Global
}

var _ kauthz.MigrationLedger = Ledger{}

// Applied is every recorded step id.
func (l Ledger) Applied(ctx context.Context) (map[string]struct{}, error) {
	q, release, err := l.Global.Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	rows, err := q.Query(ctx, `SELECT id FROM graph_migrations`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]struct{}{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out[id] = struct{}{}
	}
	return out, rows.Err()
}

// Record runs fn and records id in the same transaction.
func (l Ledger) Record(ctx context.Context, id string, fn func(ctx context.Context, q db.Querier) error) error {
	return l.Global.Write(ctx, func(ctx context.Context, q db.Querier) error {
		if err := fn(ctx, q); err != nil {
			return err
		}
		_, err := q.Exec(ctx, `INSERT INTO graph_migrations (id, applied_at) VALUES ($1, now()) ON CONFLICT (id) DO NOTHING`, id)
		return err
	})
}
