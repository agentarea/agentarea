package authz

import (
	"context"
	"fmt"
	"log/slog"
	"regexp"
	"slices"
	"sync"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// GraphProvider returns the graph. A step asks for it only when it has
// something to write: on a fresh install the migration job runs before the
// graph store is reachable, and a step with no rows must not need it.
type GraphProvider func(ctx context.Context) (Graph, error)

// OnceGraph memoises build's first success.
func OnceGraph(build func(ctx context.Context) (Graph, error)) GraphProvider {
	var (
		mu sync.Mutex
		g  Graph
	)
	return func(ctx context.Context) (Graph, error) {
		mu.Lock()
		defer mu.Unlock()
		if g != nil {
			return g, nil
		}
		built, err := build(ctx)
		if err != nil {
			return nil, err
		}
		g = built
		return g, nil
	}
}

// GraphMigration is a one-shot step that brings the graph up to the rows a
// release holds, which a schema migration cannot (rebac/graph_migrations.py).
// ID is dated like an Alembic file, YYYYMMDD_HHMM_<slug>, and orders the
// steps. Apply must be idempotent: a step interrupted between applying and
// being recorded runs again.
type GraphMigration struct {
	ID          string
	Description string
	Apply       func(ctx context.Context, q db.Querier, graph GraphProvider) error
}

// MigrationLedger is the graph_migrations table: which steps have applied.
type MigrationLedger interface {
	Applied(ctx context.Context) (map[string]struct{}, error)
	// Record runs fn in one transaction and, when fn succeeds, records id as
	// applied in the same transaction.
	Record(ctx context.Context, id string, fn func(ctx context.Context, q db.Querier) error) error
}

// CheckMigrations refuses a registry whose ids are malformed, repeated or out
// of order.
func CheckMigrations(steps []GraphMigration) error {
	pattern := regexp.MustCompile(`^[0-9]{8}_[0-9]{4}_[a-z0-9_]+$`)
	ids := make([]string, len(steps))
	for i, s := range steps {
		if !pattern.MatchString(s.ID) {
			return fmt.Errorf("graph migration id %q is not YYYYMMDD_HHMM_<slug>", s.ID)
		}
		ids[i] = s.ID
	}
	if len(slices.Compact(slices.Sorted(slices.Values(ids)))) != len(ids) {
		return fmt.Errorf("graph migration ids repeat: %v", ids)
	}
	if !slices.IsSorted(ids) {
		return fmt.Errorf("graph migrations are not in id order: %v", ids)
	}
	return nil
}

// ApplyPendingGraphMigrations applies, in id order, every step the ledger has
// not recorded, each in its own transaction, and returns the ids applied. A
// failing step stops the run unrecorded and runs again next time. `migrate`
// calls it right after the schema migration.
func ApplyPendingGraphMigrations(ctx context.Context, ledger MigrationLedger, steps []GraphMigration, graph GraphProvider, log *slog.Logger) ([]string, error) {
	if err := CheckMigrations(steps); err != nil {
		return nil, err
	}
	if log == nil {
		log = slog.Default()
	}
	applied, err := ledger.Applied(ctx)
	if err != nil {
		return nil, err
	}
	ran := []string{}
	for _, step := range steps {
		if _, done := applied[step.ID]; done {
			continue
		}
		log.InfoContext(ctx, "applying graph migration", "id", step.ID, "description", step.Description)
		err := ledger.Record(ctx, step.ID, func(ctx context.Context, q db.Querier) error {
			return step.Apply(ctx, q, graph)
		})
		if err != nil {
			return ran, fmt.Errorf("graph migration %s: %w", step.ID, err)
		}
		ran = append(ran, step.ID)
	}
	return ran, nil
}
