// Package db is the one Postgres database every role uses: a transactional
// write pool and an AUTOCOMMIT read pool (the replica when
// AGENTAREA_DB_READ_HOST is set).
//
// SQL lives only in a module's store/ and here (lint rule 4). A store gets a
// query runner only inside a Session, which carries the workspace the call
// acts in, so every store method is workspace-scoped by type (D16). Global
// tables (catalog registries, reference rows) are reached through Global,
// named so a reviewer sees it.
//
// Querier has the shape sqlc's pgx/v5 output expects (DBTX), so a store hands
// it to its generated queries unchanged.
//
// Python sets no statement_timeout on its connections; neither does this
// package. A statement that must not wait long for a lock bounds itself with
// SetLockTimeout, as the read-model partition DDL does.
package db

import (
	"context"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// Querier runs statements; sqlc's DBTX.
type Querier interface {
	Exec(ctx context.Context, sql string, args ...any) (pgconn.CommandTag, error)
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Session is a query runner bound to the workspace a call acts in.
type Session struct {
	ws scope.Workspace
	q  Querier
	tx bool
}

// NewSession binds q, a runner outside any transaction, to ws.
func NewSession(ws scope.Workspace, q Querier) Session { return Session{ws: ws, q: q} }

// NewTxSession binds q, a runner inside a transaction, to ws.
func NewTxSession(ws scope.Workspace, q Querier) Session { return Session{ws: ws, q: q, tx: true} }

// Workspace is the workspace every query of this session filters by.
func (s Session) Workspace() scope.Workspace { return s.ws }

// Q is the query runner.
func (s Session) Q() Querier { return s.q }

// InTx reports whether the session's statements commit or roll back together,
// as they do inside Database.Write.
func (s Session) InTx() bool { return s.tx }

// Database is the port the cluster profile implements over pgx pools.
type Database interface {
	// Read returns a session on the read pool (AUTOCOMMIT). One session is one
	// connection at a time: never run its queries concurrently.
	Read(ctx context.Context, ws scope.Workspace) (Session, func(), error)
	// Write runs fn in one transaction on the write pool; fn's error rolls back.
	Write(ctx context.Context, ws scope.Workspace, fn func(ctx context.Context, s Session) error) error
	// Global reaches tables that belong to no workspace.
	Global() Global
	// Lock runs fn in a transaction that first waits for the transaction-scoped
	// advisory lock key (pg_advisory_xact_lock).
	Lock(ctx context.Context, key LockKey, fn func(ctx context.Context, q Querier) error) error
	// TryLock runs fn in a transaction holding key when it is free
	// (pg_try_advisory_xact_lock) and reports false without running fn when
	// another holder has it.
	TryLock(ctx context.Context, key LockKey, fn func(ctx context.Context, q Querier) error) (bool, error)
	// TrySessionLock holds the session-level lock key (pg_try_advisory_lock)
	// on its own AUTOCOMMIT connection of the write pool while fn runs, so fn
	// holds no transaction open. It needs a direct connection or a
	// session-mode pooler.
	TrySessionLock(ctx context.Context, key LockKey, fn func(ctx context.Context, q Querier) error) (bool, error)
	Ping(ctx context.Context) error
	Close()
}

// Global is access to workspace-less tables, and to every workspace's rows
// for infrastructure that spans them (the outbox relay).
type Global interface {
	Read(ctx context.Context) (Querier, func(), error)
	Write(ctx context.Context, fn func(ctx context.Context, q Querier) error) error
}
