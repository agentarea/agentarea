package authz

import (
	"context"
	"errors"
	"os"
	"slices"
	"testing"

	"github.com/jackc/pgx/v5"         //nolint:depguard // the integration test opens its own pool; the cluster db adapter is another package
	"github.com/jackc/pgx/v5/pgxpool" //nolint:depguard // see above

	kauthz "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
)

type poolGlobal struct{ pool *pgxpool.Pool }

func (g poolGlobal) Read(ctx context.Context) (db.Querier, func(), error) {
	c, err := g.pool.Acquire(ctx)
	if err != nil {
		return nil, nil, err
	}
	return c, c.Release, nil
}

func (g poolGlobal) Write(ctx context.Context, fn func(context.Context, db.Querier) error) error {
	return pgx.BeginTxFunc(ctx, g.pool, pgx.TxOptions{}, func(tx pgx.Tx) error { return fn(ctx, tx) })
}

func openLedger(t *testing.T) (Ledger, *pgxpool.Pool) {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	if _, err := pool.Exec(context.Background(), `DELETE FROM graph_migrations WHERE id LIKE '2099%'`); err != nil {
		t.Fatal(err)
	}
	return Ledger{Global: poolGlobal{pool: pool}}, pool
}

// The steps run against the real ledger table and, when
// AGENTAREA_TEST_OPENFGA_URL is set too, write through the real graph.
func TestGraphMigrationsLedger(t *testing.T) {
	ctx := context.Background()
	ledger, pool := openLedger(t)
	var graph kauthz.GraphProvider = func(context.Context) (kauthz.Graph, error) {
		return nil, errors.New("no graph configured")
	}
	var c *Client
	if os.Getenv("AGENTAREA_TEST_OPENFGA_URL") != "" {
		c, _ = openGraph(t)
		graph = kauthz.OnceGraph(func(context.Context) (kauthz.Graph, error) { return c, nil })
	}

	var ran []string
	marker := func(id string, fail bool) kauthz.GraphMigration {
		return kauthz.GraphMigration{ID: id, Description: "test", Apply: func(ctx context.Context, q db.Querier, provider kauthz.GraphProvider) error {
			ran = append(ran, id)
			if _, err := q.Exec(ctx, `SELECT 1`); err != nil {
				return err
			}
			if fail {
				return errors.New("boom")
			}
			if c == nil {
				return nil
			}
			g, err := provider(ctx)
			if err != nil {
				return err
			}
			return kauthz.GrantResourceOwner(ctx, g, id, "w1", "User:u1", kauthz.OwnerRelations())
		}}
	}

	steps := []kauthz.GraphMigration{marker("20990101_0000_first", false), marker("20990102_0000_broken", true), marker("20990103_0000_third", false)}
	applied, err := kauthz.ApplyPendingGraphMigrations(ctx, ledger, steps, graph, nil)
	if err == nil || !slices.Equal(applied, []string{"20990101_0000_first"}) {
		t.Fatalf("applied %v, err %v", applied, err)
	}
	recorded, err := ledger.Applied(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := recorded["20990101_0000_first"]; !ok {
		t.Fatal("first step not recorded")
	}
	if _, ok := recorded["20990102_0000_broken"]; ok {
		t.Fatal("failed step recorded")
	}

	steps[1] = marker("20990102_0000_broken", false)
	ran = nil
	applied, err = kauthz.ApplyPendingGraphMigrations(ctx, ledger, steps, graph, nil)
	if err != nil || !slices.Equal(applied, []string{"20990102_0000_broken", "20990103_0000_third"}) || !slices.Equal(ran, applied) {
		t.Fatalf("second run applied %v ran %v err %v", applied, ran, err)
	}
	var stamped int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM graph_migrations WHERE id LIKE '2099%' AND applied_at IS NOT NULL`).Scan(&stamped); err != nil || stamped != 3 {
		t.Fatalf("rows = %d %v", stamped, err)
	}
	if applied, err := kauthz.ApplyPendingGraphMigrations(ctx, ledger, steps, graph, nil); err != nil || len(applied) != 0 {
		t.Fatalf("third run applied %v %v", applied, err)
	}
	if c != nil {
		ok, err := c.Check(ctx, "User:u1", kauthz.CanManage, kauthz.TypeResource, "20990103_0000_third")
		if err != nil || !ok {
			t.Fatalf("step's grant not in the graph: %v %v", ok, err)
		}
	}

	rollback := kauthz.GraphMigration{ID: "20990104_0000_rollback", Apply: func(ctx context.Context, q db.Querier, _ kauthz.GraphProvider) error {
		if _, err := q.Exec(ctx, `INSERT INTO graph_migrations (id, applied_at) VALUES ('20990104_9999_inside', now())`); err != nil {
			return err
		}
		return errors.New("boom")
	}}
	if _, err := kauthz.ApplyPendingGraphMigrations(ctx, ledger, []kauthz.GraphMigration{rollback}, graph, nil); err == nil {
		t.Fatal("failing step succeeded")
	}
	var inside int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM graph_migrations WHERE id LIKE '20990104%'`).Scan(&inside); err != nil || inside != 0 {
		t.Fatalf("a failed step's writes were committed: %d %v", inside, err)
	}
}
