// Package schema owns the database schema: the goose migration sets that
// continue the Python Alembic history, starting from a baseline equal to the
// last Alembic head.
package schema

import (
	"context"
	"database/sql"
	"embed"
	"errors"
	"fmt"
	"io/fs"
	"strings"

	_ "github.com/jackc/pgx/v5/stdlib" // registers the "pgx" database/sql driver
	"github.com/pressly/goose/v3"
	"github.com/pressly/goose/v3/database"
)

// AlembicHead is the last core Alembic revision; the core baseline equals the
// schema and reference rows `alembic upgrade head` leaves at it.
const AlembicHead = "20261111_1200_source_senders"

// BaselineVersion is the goose version of each set's baseline file.
const BaselineVersion int64 = 1

//go:embed migrations/*.sql
var coreFiles embed.FS

// CoreMigrations is the core goose set, files at its root.
func CoreMigrations() fs.FS { return mustSub(coreFiles, "migrations") }

// Set is one goose migration set and the Alembic stream it continues.
type Set struct {
	Name string
	// Migrations holds the goose files at its root.
	Migrations fs.FS
	// Schema is where the set's objects live. It is created before goose runs
	// when CreateSchema is set, and a database is fresh for the set when the
	// schema holds no relation.
	Schema       string
	CreateSchema bool
	// VersionTable is goose's schema-qualified version table.
	VersionTable string
	// AlembicTable is the schema-qualified Alembic version table this set takes over.
	AlembicTable string
	AlembicHead  string
	// LockKey names the advisory lock that serializes concurrent migrators.
	LockKey string
	// UpTo stops goose at this version; 0 runs every file.
	UpTo int64
}

// Core is the core set.
func Core() Set {
	return Set{
		Name:         "core",
		Migrations:   CoreMigrations(),
		Schema:       "public",
		VersionTable: "public.goose_db_version",
		AlembicTable: "public.alembic_version",
		AlembicHead:  AlembicHead,
		LockKey:      "agentarea_schema_core",
	}
}

// Extension is a set an extension registers (ext.WithMigrations): its objects
// in their own schema, created when absent, goose's table and the lock named
// after it. alembicTable and alembicHead are empty for a set that continues no
// Alembic stream.
func Extension(name string, migrations fs.FS, schemaName, alembicTable, alembicHead string) Set {
	return Set{
		Name:         name,
		Migrations:   migrations,
		Schema:       schemaName,
		CreateSchema: true,
		VersionTable: schemaName + ".goose_db_version",
		AlembicTable: alembicTable,
		AlembicHead:  alembicHead,
		LockKey:      "agentarea_schema_" + name,
	}
}

// Open opens a database/sql handle on the pgx driver.
func Open(dsn string) (*sql.DB, error) {
	return sql.Open("pgx", dsn)
}

// Migrate brings the set to its latest goose version, or to set.UpTo.
//
// A database the Python migrations built must stand at the set's Alembic
// head: the baseline is then recorded as applied without running. Any other
// Alembic revision is refused with an error naming it. A database whose schema
// holds no relation gets the baseline applied. A schema that holds relations
// but neither version table is refused.
func Migrate(ctx context.Context, db *sql.DB, set Set) error {
	conn, err := db.Conn(ctx)
	if err != nil {
		return fmt.Errorf("schema %s: %w", set.Name, err)
	}
	defer func() { _ = conn.Close() }()

	if _, err := conn.ExecContext(ctx, "SELECT pg_advisory_lock(hashtext($1))", set.LockKey); err != nil {
		return fmt.Errorf("schema %s: lock: %w", set.Name, err)
	}
	defer func() {
		_, _ = conn.ExecContext(context.WithoutCancel(ctx), "SELECT pg_advisory_unlock(hashtext($1))", set.LockKey)
	}()

	if set.CreateSchema {
		if _, err := conn.ExecContext(ctx, "CREATE SCHEMA IF NOT EXISTS "+quoteIdent(set.Schema)); err != nil {
			return fmt.Errorf("schema %s: create schema: %w", set.Name, err)
		}
	}

	store, err := database.NewStore(database.DialectPostgres, set.VersionTable)
	if err != nil {
		return fmt.Errorf("schema %s: %w", set.Name, err)
	}

	var alembic []string
	if set.AlembicTable != "" {
		if alembic, err = alembicRevisions(ctx, conn, set.AlembicTable); err != nil {
			return fmt.Errorf("schema %s: %w", set.Name, err)
		}
	}
	if alembic != nil && (len(alembic) != 1 || alembic[0] != set.AlembicHead) {
		return &RevisionError{Set: set.Name, Revisions: alembic, Head: set.AlembicHead}
	}

	tracked, err := relationExists(ctx, conn, set.VersionTable)
	if err != nil {
		return fmt.Errorf("schema %s: %w", set.Name, err)
	}
	if !tracked {
		switch {
		case alembic != nil:
			if err := stamp(ctx, conn, store); err != nil {
				return fmt.Errorf("schema %s: record baseline: %w", set.Name, err)
			}
		default:
			n, err := relationCount(ctx, conn, set.Schema)
			if err != nil {
				return fmt.Errorf("schema %s: %w", set.Name, err)
			}
			if n > 0 {
				return fmt.Errorf("schema %s: %s holds %d relations but neither %s nor %s; refusing to migrate it",
					set.Name, set.Schema, n, set.AlembicTable, set.VersionTable)
			}
		}
	}

	provider, err := goose.NewProvider("", db, set.Migrations, goose.WithStore(store), goose.WithDisableGlobalRegistry(true))
	if err != nil {
		return fmt.Errorf("schema %s: %w", set.Name, err)
	}
	if set.UpTo > 0 {
		_, err = provider.UpTo(ctx, set.UpTo)
	} else {
		_, err = provider.Up(ctx)
	}
	if err != nil {
		return fmt.Errorf("schema %s: %w", set.Name, err)
	}
	return nil
}

// State is where a database stands for one set, read without changing it.
type State struct {
	Set string
	// Tracked is whether the set's goose version table exists; Current is its
	// version then, and Alembic the revisions of the Alembic stream it continues otherwise.
	Tracked bool
	Current int64
	Alembic []string
	// Head is the set's latest goose version, and Pending whether any file is unapplied.
	Head    int64
	Pending bool
}

// UpToDate is whether Migrate has nothing left to do for the set.
func (s State) UpToDate() bool { return s.Tracked && !s.Pending }

// Status reads where db stands for set (check_migrations).
func Status(ctx context.Context, db *sql.DB, set Set) (State, error) {
	st := State{Set: set.Name}
	conn, err := db.Conn(ctx)
	if err != nil {
		return st, fmt.Errorf("schema %s: %w", set.Name, err)
	}
	defer func() { _ = conn.Close() }()
	if st.Tracked, err = relationExists(ctx, conn, set.VersionTable); err != nil {
		return st, fmt.Errorf("schema %s: %w", set.Name, err)
	}
	store, err := database.NewStore(database.DialectPostgres, set.VersionTable)
	if err != nil {
		return st, fmt.Errorf("schema %s: %w", set.Name, err)
	}
	provider, err := goose.NewProvider("", db, set.Migrations, goose.WithStore(store), goose.WithDisableGlobalRegistry(true))
	if err != nil {
		return st, fmt.Errorf("schema %s: %w", set.Name, err)
	}
	sources := provider.ListSources()
	if len(sources) > 0 {
		st.Head = sources[len(sources)-1].Version
	}
	if !st.Tracked {
		st.Pending = true
		if set.AlembicTable != "" {
			if st.Alembic, err = alembicRevisions(ctx, conn, set.AlembicTable); err != nil {
				return st, fmt.Errorf("schema %s: %w", set.Name, err)
			}
		}
		return st, nil
	}
	if st.Current, err = provider.GetDBVersion(ctx); err != nil {
		return st, fmt.Errorf("schema %s: %w", set.Name, err)
	}
	if st.Pending, err = provider.HasPending(ctx); err != nil {
		return st, fmt.Errorf("schema %s: %w", set.Name, err)
	}
	return st, nil
}

// RevisionError is returned for a database at an Alembic revision other than the head.
type RevisionError struct {
	Set       string
	Revisions []string
	Head      string
}

func (e *RevisionError) Error() string {
	got := "no revision"
	if len(e.Revisions) > 0 {
		got = "revision " + strings.Join(e.Revisions, ", ")
	}
	return fmt.Sprintf("schema %s: database is at Alembic %s, not %s; run the Python migrations to %s first",
		e.Set, got, e.Head, e.Head)
}

// stamp records the baseline as applied: the version table with goose's zero
// row and the baseline row, in one transaction.
func stamp(ctx context.Context, conn *sql.Conn, store database.Store) error {
	tx, err := conn.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	if err := store.CreateVersionTable(ctx, tx); err != nil {
		return err
	}
	for _, v := range []int64{0, BaselineVersion} {
		if err := store.Insert(ctx, tx, database.InsertRequest{Version: v}); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// alembicRevisions returns nil when the table does not exist.
func alembicRevisions(ctx context.Context, conn *sql.Conn, table string) ([]string, error) {
	ok, err := relationExists(ctx, conn, table)
	if err != nil || !ok {
		return nil, err
	}
	rows, err := conn.QueryContext(ctx, "SELECT version_num FROM "+quoteQualified(table)+" ORDER BY version_num")
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	revisions := []string{}
	for rows.Next() {
		var r string
		if err := rows.Scan(&r); err != nil {
			return nil, err
		}
		revisions = append(revisions, r)
	}
	return revisions, rows.Err()
}

func relationExists(ctx context.Context, conn *sql.Conn, qualified string) (bool, error) {
	var ok bool
	err := conn.QueryRowContext(ctx, "SELECT to_regclass($1) IS NOT NULL", quoteQualified(qualified)).Scan(&ok)
	return ok, err
}

func relationCount(ctx context.Context, conn *sql.Conn, schema string) (int, error) {
	var n int
	err := conn.QueryRowContext(ctx, `
		SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
		WHERE n.nspname = $1 AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
		AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e')`,
		schema).Scan(&n)
	return n, err
}

func quoteIdent(s string) string {
	return `"` + strings.ReplaceAll(s, `"`, `""`) + `"`
}

func quoteQualified(s string) string {
	schema, name, ok := strings.Cut(s, ".")
	if !ok {
		return quoteIdent(s)
	}
	return quoteIdent(schema) + "." + quoteIdent(name)
}

func mustSub(f fs.FS, dir string) fs.FS {
	sub, err := fs.Sub(f, dir)
	if err != nil {
		panic(errors.Join(fmt.Errorf("schema: embedded %s", dir), err))
	}
	return sub
}
