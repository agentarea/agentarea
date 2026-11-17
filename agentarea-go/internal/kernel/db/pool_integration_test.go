package db

import (
	"context"
	"errors"
	"log/slog"
	"net/url"
	"os"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

var (
	_ Querier = pgx.Tx(nil)
	_ Querier = (*pgxpool.Conn)(nil)
	_ Querier = (*pgxpool.Pool)(nil)
)

// testConfig is AGENTAREA_DB_TEST_URL as a Config; the test is skipped without it.
func testConfig(t *testing.T) Config {
	t.Helper()
	raw := os.Getenv("AGENTAREA_DB_TEST_URL")
	if raw == "" {
		t.Skip("AGENTAREA_DB_TEST_URL not set")
	}
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(u.Port())
	pw, _ := u.User.Password()
	return Config{
		Host: u.Hostname(), Port: port, Name: u.Path[1:], User: u.User.Username(), Password: pw,
		SSLMode: u.Query().Get("sslmode"), PoolSize: 5, PoolOverflow: 5, PoolTimeout: 5 * time.Second, PoolRecycle: time.Hour,
	}
}

// freshDatabase creates an empty database for the test and drops it after.
func freshDatabase(t *testing.T) Config {
	t.Helper()
	admin := testConfig(t)
	ctx := context.Background()
	p, err := Open(ctx, admin, slog.Default())
	if err != nil {
		t.Fatal(err)
	}
	name := "aa_go_db_" + uuid.NewString()[:8]
	q, release, err := p.Global().Read(ctx)
	if err != nil {
		t.Fatal(err)
	}
	_, err = q.Exec(ctx, "CREATE DATABASE "+name)
	release()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		q, release, err := p.Global().Read(ctx)
		if err == nil {
			_, _ = q.Exec(ctx, "DROP DATABASE "+name+" WITH (FORCE)")
			release()
		}
		p.Close()
	})
	c := admin
	c.Name = name
	return c
}

func openTest(t *testing.T, c Config) *Pools {
	t.Helper()
	p, err := Open(context.Background(), c, slog.Default())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(p.Close)
	return p
}

func ws(t *testing.T) scope.Workspace {
	w, err := scope.NewWorkspace("ws-"+uuid.NewString()[:6], "")
	if err != nil {
		t.Fatal(err)
	}
	return w
}

func TestReadIsAutocommitWriteIsTransaction(t *testing.T) {
	p := openTest(t, freshDatabase(t))
	ctx := context.Background()
	w := ws(t)

	s, release, err := p.Read(ctx, w)
	if err != nil {
		t.Fatal(err)
	}
	if s.InTx() || s.Workspace() != w {
		t.Errorf("read session: tx=%v ws=%v", s.InTx(), s.Workspace())
	}
	sameTx, err := oneTransaction(ctx, s.Q())
	if err != nil {
		t.Fatal(err)
	}
	release()
	if sameTx {
		t.Error("read session statements share a transaction; want AUTOCOMMIT")
	}

	err = p.Write(ctx, w, func(ctx context.Context, s Session) error {
		if !s.InTx() {
			t.Error("write session is not in a transaction")
		}
		sameTx, err = oneTransaction(ctx, s.Q())
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	if !sameTx {
		t.Error("write session statements are not one transaction")
	}
	if _, _, err := p.Read(ctx, scope.Workspace{}); !errors.Is(err, scope.ErrNoWorkspace) {
		t.Errorf("zero workspace: %v", err)
	}
}

func TestWriteRollsBackOnError(t *testing.T) {
	p := openTest(t, freshDatabase(t))
	ctx := context.Background()
	if err := p.Global().Write(ctx, func(ctx context.Context, q Querier) error {
		_, err := q.Exec(ctx, "CREATE TABLE t (n int)")
		return err
	}); err != nil {
		t.Fatal(err)
	}
	boom := errors.New("boom")
	err := p.Write(ctx, ws(t), func(ctx context.Context, s Session) error {
		if _, err := s.Q().Exec(ctx, "INSERT INTO t VALUES (1)"); err != nil {
			return err
		}
		return boom
	})
	if !errors.Is(err, boom) {
		t.Fatalf("err = %v", err)
	}
	q, release, err := p.Global().Read(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	var n int
	if err := q.QueryRow(ctx, "SELECT count(*) FROM t").Scan(&n); err != nil || n != 0 {
		t.Errorf("rows after rollback = %d, %v", n, err)
	}
}

// oneTransaction reports whether two statements on q ran in one transaction.
func oneTransaction(ctx context.Context, q Querier) (bool, error) {
	var a, b int64
	if err := q.QueryRow(ctx, "SELECT txid_current()").Scan(&a); err != nil {
		return false, err
	}
	err := q.QueryRow(ctx, "SELECT txid_current()").Scan(&b)
	return a == b, err
}

// holdLock keeps the lock sql takes in an open transaction until release is called.
func holdLock(t *testing.T, p *Pools, sql string, args ...any) (release func()) {
	t.Helper()
	held, done := make(chan struct{}), make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		err := p.Global().Write(context.Background(), func(ctx context.Context, q Querier) error {
			if _, err := q.Exec(ctx, sql, args...); err != nil {
				return err
			}
			close(held)
			<-done
			return nil
		})
		if err != nil {
			t.Error(err)
		}
	}()
	select {
	case <-held:
	case <-time.After(5 * time.Second):
		t.Fatal("lock not taken")
	}
	return func() { close(done); wg.Wait() }
}

func TestAdvisoryLocks(t *testing.T) {
	p := openTest(t, freshDatabase(t))
	ctx := context.Background()
	noop := func(context.Context, Querier) error { return nil }

	cases := []struct {
		key  LockKey
		sql  string
		args []any
	}{
		{Key(798_021_335_641), "SELECT pg_advisory_xact_lock(798021335641)", nil},
		{TextKey("registry:core"), "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", []any{"registry:core"}},
		{PairKey(0x53455131, "6f1c2a7e-3c1b-4b8e-9a51-2f4f0d1c9e10"), "SELECT pg_advisory_xact_lock(1397051697, hashtext($1))", []any{"6f1c2a7e-3c1b-4b8e-9a51-2f4f0d1c9e10"}},
	}
	for _, c := range cases {
		release := holdLock(t, p, c.sql, c.args...)
		held, err := p.TryLock(ctx, c.key, func(context.Context, Querier) error { t.Errorf("%s ran while held", c.key); return nil })
		if err != nil || held {
			t.Errorf("TryLock(%s) while held = %v, %v", c.key, held, err)
		}
		if held, err := p.TrySessionLock(ctx, c.key, noop); err != nil || held {
			t.Errorf("TrySessionLock(%s) while held = %v, %v", c.key, held, err)
		}
		release()
		if held, err := p.TryLock(ctx, c.key, noop); err != nil || !held {
			t.Errorf("TryLock(%s) when free = %v, %v", c.key, held, err)
		}
	}

	release := holdLock(t, p, "SELECT pg_advisory_xact_lock(7)")
	got := make(chan error, 1)
	go func() { got <- p.Lock(ctx, Key(7), noop) }()
	select {
	case err := <-got:
		t.Errorf("Lock did not wait for the holder (%v)", err)
	case <-time.After(200 * time.Millisecond):
	}
	release()
	if err := <-got; err != nil {
		t.Error(err)
	}

	err := func() error {
		_, err := p.TrySessionLock(ctx, TextKey("s"), func(ctx context.Context, _ Querier) error {
			held, err := p.TryLock(ctx, TextKey("s"), noop)
			if err != nil {
				return err
			}
			if held {
				return errors.New("session lock not held")
			}
			return nil
		})
		return err
	}()
	if err != nil {
		t.Error(err)
	}
	if held, err := p.TryLock(ctx, TextKey("s"), noop); err != nil || !held {
		t.Errorf("session lock not released: %v %v", held, err)
	}
}

func TestLockTimeout(t *testing.T) {
	p := openTest(t, freshDatabase(t))
	ctx := context.Background()
	if err := p.Global().Write(ctx, func(ctx context.Context, q Querier) error {
		_, err := q.Exec(ctx, "CREATE TABLE t (n int)")
		return err
	}); err != nil {
		t.Fatal(err)
	}
	release := holdLock(t, p, "LOCK TABLE t IN ACCESS EXCLUSIVE MODE")
	defer release()
	err := p.Global().Write(ctx, func(ctx context.Context, q Querier) error {
		if err := SetLockTimeout(ctx, q, 100*time.Millisecond); err != nil {
			return err
		}
		_, err := q.Exec(ctx, "LOCK TABLE t IN ACCESS EXCLUSIVE MODE")
		return err
	})
	if !IsLockNotAvailable(err) {
		t.Errorf("err = %v, want lock_not_available", err)
	}
}

func TestPoolTimeout(t *testing.T) {
	c := freshDatabase(t)
	c.PoolSize, c.PoolOverflow, c.PoolTimeout = 1, 0, 200*time.Millisecond
	p := openTest(t, c)
	ctx := context.Background()
	_, release, err := p.Read(ctx, ws(t))
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	start := time.Now()
	if _, _, err := p.Read(ctx, ws(t)); !errors.Is(err, ErrPoolTimeout) {
		t.Errorf("second session = %v, want ErrPoolTimeout", err)
	}
	if waited := time.Since(start); waited < 150*time.Millisecond || waited > 2*time.Second {
		t.Errorf("waited %s for a 200ms pool timeout", waited)
	}
}
