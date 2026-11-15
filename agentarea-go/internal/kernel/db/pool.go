package db

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// ErrPoolTimeout: no connection came free within AGENTAREA_DB_POOL_TIMEOUT.
var ErrPoolTimeout = errors.New("timed out waiting for a database connection")

// Pools is Database over pgx pools, sized as config/database.py sizes
// SQLAlchemy's: at most POOL_SIZE+POOL_OVERFLOW connections, recycled after
// POOL_RECYCLE, checked on checkout (pgx pings a connection idle over a
// second), POOL_TIMEOUT to wait for one. Without a replica the read side
// shares the write pool and runs its statements in AUTOCOMMIT.
//
// It lives here rather than in profiles/cluster because lint rule 4 admits
// pgx only in kernel/db and store/.
type Pools struct {
	write   *pgxpool.Pool
	read    *pgxpool.Pool
	timeout time.Duration
}

var _ Database = (*Pools)(nil)

// Open connects the pools; it does not wait for a first connection.
func Open(ctx context.Context, c Config, log *slog.Logger) (*Pools, error) {
	write, err := newPool(ctx, c, c.WriteURL(), c.PoolSize+c.PoolOverflow, log)
	if err != nil {
		return nil, fmt.Errorf("write pool: %w", err)
	}
	p := &Pools{write: write, read: write, timeout: c.PoolTimeout}
	if c.ReadHost != "" {
		read, err := newPool(ctx, c, c.ReadURL(), c.ReadPoolSize+c.ReadPoolOverflow, log)
		if err != nil {
			write.Close()
			return nil, fmt.Errorf("read pool: %w", err)
		}
		p.read = read
	}
	return p, nil
}

func newPool(ctx context.Context, c Config, url string, maxConns int, log *slog.Logger) (*pgxpool.Pool, error) {
	pc, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, err
	}
	if maxConns < 1 {
		return nil, fmt.Errorf("pool of %d connections", maxConns)
	}
	pc.MaxConns = int32(min(maxConns, 1<<30)) //nolint:gosec // bounded above
	pc.MinConns = 0
	if c.PoolRecycle > 0 {
		pc.MaxConnLifetime = c.PoolRecycle
	}
	if c.Echo && log != nil {
		pc.ConnConfig.Tracer = echoTracer{log: log}
	}
	return pgxpool.NewWithConfig(ctx, pc)
}

type echoTracer struct{ log *slog.Logger }

func (t echoTracer) TraceQueryStart(ctx context.Context, _ *pgx.Conn, d pgx.TraceQueryStartData) context.Context {
	t.log.InfoContext(ctx, "sql", "statement", d.SQL)
	return ctx
}

func (echoTracer) TraceQueryEnd(context.Context, *pgx.Conn, pgx.TraceQueryEndData) {}

func (p *Pools) acquire(ctx context.Context, pool *pgxpool.Pool) (*pgxpool.Conn, error) {
	actx := ctx
	if p.timeout > 0 {
		var cancel context.CancelFunc
		actx, cancel = context.WithTimeout(ctx, p.timeout)
		defer cancel()
	}
	conn, err := pool.Acquire(actx)
	if err != nil {
		if ctx.Err() == nil && errors.Is(actx.Err(), context.DeadlineExceeded) {
			return nil, fmt.Errorf("%w after %s", ErrPoolTimeout, p.timeout)
		}
		return nil, err
	}
	return conn, nil
}

func (p *Pools) inTx(ctx context.Context, pool *pgxpool.Pool, fn func(ctx context.Context, tx pgx.Tx) error) (err error) {
	conn, err := p.acquire(ctx, pool)
	if err != nil {
		return err
	}
	defer conn.Release()
	tx, err := conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() {
		if r := recover(); r != nil {
			_ = tx.Rollback(context.WithoutCancel(ctx))
			panic(r)
		}
		if err != nil {
			if rbErr := tx.Rollback(context.WithoutCancel(ctx)); rbErr != nil && !errors.Is(rbErr, pgx.ErrTxClosed) {
				err = errors.Join(err, fmt.Errorf("rollback: %w", rbErr))
			}
		}
	}()
	if err = fn(ctx, tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// Read is an AUTOCOMMIT session: no BEGIN is sent, each statement commits alone.
func (p *Pools) Read(ctx context.Context, ws scope.Workspace) (Session, func(), error) {
	if ws.IsZero() {
		return Session{}, nil, scope.ErrNoWorkspace
	}
	conn, err := p.acquire(ctx, p.read)
	if err != nil {
		return Session{}, nil, err
	}
	return NewSession(ws, conn), conn.Release, nil
}

func (p *Pools) Write(ctx context.Context, ws scope.Workspace, fn func(ctx context.Context, s Session) error) error {
	if ws.IsZero() {
		return scope.ErrNoWorkspace
	}
	return p.inTx(ctx, p.write, func(ctx context.Context, tx pgx.Tx) error {
		return fn(ctx, NewTxSession(ws, tx))
	})
}

func (p *Pools) Global() Global { return global{p} }

func (p *Pools) Lock(ctx context.Context, key LockKey, fn func(ctx context.Context, q Querier) error) error {
	return p.inTx(ctx, p.write, func(ctx context.Context, tx pgx.Tx) error {
		if err := XactLock(ctx, tx, key); err != nil {
			return err
		}
		return fn(ctx, tx)
	})
}

func (p *Pools) TryLock(ctx context.Context, key LockKey, fn func(ctx context.Context, q Querier) error) (bool, error) {
	var held bool
	err := p.inTx(ctx, p.write, func(ctx context.Context, tx pgx.Tx) error {
		var err error
		if held, err = TryXactLock(ctx, tx, key); err != nil || !held {
			return err
		}
		return fn(ctx, tx)
	})
	return held, err
}

func (p *Pools) TrySessionLock(ctx context.Context, key LockKey, fn func(ctx context.Context, q Querier) error) (held bool, err error) {
	conn, err := p.acquire(ctx, p.write)
	if err != nil {
		return false, err
	}
	defer conn.Release()
	if held, err = tryLock(ctx, conn, key, "pg_try_advisory_lock"); err != nil || !held {
		return false, err
	}
	defer func() {
		if uerr := unlock(context.WithoutCancel(ctx), conn, key); uerr != nil {
			// The lock goes with its connection; closing it frees the lock.
			_ = conn.Conn().Close(context.WithoutCancel(ctx))
			err = errors.Join(err, fmt.Errorf("release advisory lock %s: %w", key, uerr))
		}
	}()
	return true, fn(ctx, conn)
}

func (p *Pools) Ping(ctx context.Context) error {
	if err := p.write.Ping(ctx); err != nil {
		return fmt.Errorf("write pool: %w", err)
	}
	if p.read != p.write {
		if err := p.read.Ping(ctx); err != nil {
			return fmt.Errorf("read pool: %w", err)
		}
	}
	return nil
}

func (p *Pools) Close() {
	if p.read != p.write {
		p.read.Close()
	}
	p.write.Close()
}

type global struct{ p *Pools }

func (g global) Read(ctx context.Context) (Querier, func(), error) {
	conn, err := g.p.acquire(ctx, g.p.read)
	if err != nil {
		return nil, nil, err
	}
	return conn, conn.Release, nil
}

func (g global) Write(ctx context.Context, fn func(ctx context.Context, q Querier) error) error {
	return g.p.inTx(ctx, g.p.write, func(ctx context.Context, tx pgx.Tx) error { return fn(ctx, tx) })
}
