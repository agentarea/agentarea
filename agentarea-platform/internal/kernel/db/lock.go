package db

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5/pgconn"
)

type lockKind int

const (
	lockBigint lockKind = iota
	lockText
	lockPair
)

// LockKey names an advisory lock in one of three forms.
type LockKey struct {
	kind  lockKind
	n     int64
	class int32
	text  string
}

// Key is a bigint key, e.g. the partition pass (partitions.py) and the
// analytics pulse (pulse_repository.py) fixed keys.
func Key(n int64) LockKey { return LockKey{kind: lockBigint, n: n} }

// TextKey is hashtextextended(text, 0), the registry sync lock (agentarea_api/cli.py).
func TextKey(text string) LockKey { return LockKey{kind: lockText, text: text} }

// PairKey is (class, hashtext(text)), the stream event insert lock
// (event_repository.py, class 0x53455131 keyed by stream id).
func PairKey(class int32, text string) LockKey {
	return LockKey{kind: lockPair, class: class, text: text}
}

func (k LockKey) String() string {
	switch k.kind {
	case lockText:
		return "hashtextextended(" + strconv.Quote(k.text) + ", 0)"
	case lockPair:
		return fmt.Sprintf("(%d, hashtext(%s))", k.class, strconv.Quote(k.text))
	case lockBigint:
	}
	return strconv.FormatInt(k.n, 10)
}

func (k LockKey) call(fn string) (string, []any) {
	switch k.kind {
	case lockText:
		return "SELECT " + fn + "(hashtextextended($1::text, 0))", []any{k.text}
	case lockPair:
		return "SELECT " + fn + "($1::integer, hashtext($2::text))", []any{k.class, k.text}
	case lockBigint:
	}
	return "SELECT " + fn + "($1::bigint)", []any{k.n}
}

// XactLock waits for key until the transaction q runs in ends.
func XactLock(ctx context.Context, q Querier, key LockKey) error {
	sql, args := key.call("pg_advisory_xact_lock")
	if _, err := q.Exec(ctx, sql, args...); err != nil {
		return fmt.Errorf("advisory lock %s: %w", key, err)
	}
	return nil
}

// TryXactLock takes key until the transaction q runs in ends, if it is free.
func TryXactLock(ctx context.Context, q Querier, key LockKey) (bool, error) {
	return tryLock(ctx, q, key, "pg_try_advisory_xact_lock")
}

func tryLock(ctx context.Context, q Querier, key LockKey, fn string) (bool, error) {
	sql, args := key.call(fn)
	var held bool
	if err := q.QueryRow(ctx, sql, args...).Scan(&held); err != nil {
		return false, fmt.Errorf("advisory lock %s: %w", key, err)
	}
	return held, nil
}

func unlock(ctx context.Context, q Querier, key LockKey) error {
	sql, args := key.call("pg_advisory_unlock")
	_, err := q.Exec(ctx, sql, args...)
	return err
}

// SetLockTimeout bounds how long the rest of the transaction waits for a lock,
// as set_config('lock_timeout', '<ms>ms', true) (partitions.py _ddl). A wait
// that runs out fails with an error IsLockNotAvailable reports.
func SetLockTimeout(ctx context.Context, q Querier, d time.Duration) error {
	_, err := q.Exec(ctx, "SELECT set_config('lock_timeout', $1, true)", strconv.FormatInt(d.Milliseconds(), 10)+"ms")
	return err
}

// IsLockNotAvailable reports a lock wait that ran out (SQLSTATE 55P03).
func IsLockNotAvailable(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "55P03"
}
