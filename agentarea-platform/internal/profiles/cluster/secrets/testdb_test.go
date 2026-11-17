package secrets

import (
	"context"
	"os"
	"testing"

	"github.com/jackc/pgx/v5"         //nolint:depguard // see above
	"github.com/jackc/pgx/v5/pgxpool" //nolint:depguard // the integration test opens its own pool; the cluster db adapter is another package

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
)

// testDB is a db.Database over one pgx pool, enough for these tests.
type testDB struct{ pool *pgxpool.Pool }

func (d testDB) Read(ctx context.Context, ws scope.Workspace) (db.Session, func(), error) {
	c, err := d.pool.Acquire(ctx)
	if err != nil {
		return db.Session{}, nil, err
	}
	return db.NewSession(ws, c), c.Release, nil
}

func (d testDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	tx, err := d.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return err
	}
	if err := fn(ctx, db.NewTxSession(ws, tx)); err != nil {
		_ = tx.Rollback(ctx)
		return err
	}
	return tx.Commit(ctx)
}

func (d testDB) Global() db.Global { return nil }
func (d testDB) Lock(context.Context, db.LockKey, func(context.Context, db.Querier) error) error {
	return nil
}

func (d testDB) TryLock(context.Context, db.LockKey, func(context.Context, db.Querier) error) (bool, error) {
	return false, nil
}

func (d testDB) TrySessionLock(context.Context, db.LockKey, func(context.Context, db.Querier) error) (bool, error) {
	return false, nil
}

func (d testDB) Ping(ctx context.Context) error { return d.pool.Ping(ctx) }
func (d testDB) Close()                         { d.pool.Close() }

// openTestDB migrates the goose baseline onto AGENTAREA_DB_TEST_URL and
// skips when it is unset.
func openTestDB(t *testing.T) testDB {
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
	return testDB{pool: pool}
}
