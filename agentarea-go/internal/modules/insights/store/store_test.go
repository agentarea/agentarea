package store

import (
	"context"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

// pgGlobal is db.Global over a pool: each write runs in one transaction.
type pgGlobal struct{ pool *pgxpool.Pool }

func (g pgGlobal) Read(context.Context) (db.Querier, func(), error) {
	panic("insights reads the installation through Write only")
}

func (g pgGlobal) Write(ctx context.Context, fn func(ctx context.Context, q db.Querier) error) error {
	tx, err := g.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return err
	}
	if err := fn(ctx, tx); err != nil {
		_ = tx.Rollback(ctx)
		return err
	}
	return tx.Commit(ctx)
}

func openPool(t *testing.T) *pgxpool.Pool {
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
	if _, err := pool.Exec(context.Background(), `DELETE FROM installation`); err != nil {
		t.Fatal(err)
	}
	return pool
}

func TestGetOrCreateKeepsOneRowAndStoresUTC(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	g := pgGlobal{pool}
	var inst Installation
	local := time.Date(2026, 11, 12, 13, 0, 0, 0, time.FixedZone("UTC+3", 3*3600))
	id, err := inst.GetOrCreate(ctx, g, local)
	if err != nil || len(id) != 32 {
		t.Fatalf("first call: %q %v", id, err)
	}
	again, err := inst.GetOrCreate(ctx, g, local.Add(time.Hour))
	if err != nil || again != id {
		t.Fatalf("second call: %q %v, want %q", again, err, id)
	}
	var rows int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM installation`).Scan(&rows); err != nil || rows != 1 {
		t.Fatalf("rows %d %v", rows, err)
	}
	var created time.Time
	if err := pool.QueryRow(ctx, `SELECT created_at FROM installation`).Scan(&created); err != nil {
		t.Fatal(err)
	}
	if want := time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC); !created.Equal(want) {
		t.Fatalf("created_at %v, want the UTC wall clock %v", created, want)
	}
}

func TestConcurrentCallersShareOneRow(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	g := pgGlobal{pool}
	var inst Installation
	ids := make([]string, 8)
	errs := make([]error, 8)
	var wg sync.WaitGroup
	for i := range ids {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			ids[i], errs[i] = inst.GetOrCreate(ctx, g, time.Now())
		}(i)
	}
	wg.Wait()
	for i := range ids {
		if errs[i] != nil || ids[i] != ids[0] {
			t.Fatalf("caller %d: %q %v, want %q", i, ids[i], errs[i], ids[0])
		}
	}
	var rows int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM installation`).Scan(&rows); err != nil || rows != 1 {
		t.Fatalf("rows %d %v", rows, err)
	}
}
