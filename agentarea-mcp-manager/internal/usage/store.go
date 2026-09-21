package usage

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

var ErrIdentityCollision = errors.New("usage event identity has different immutable content")

type Store struct {
	db *sql.DB
}

type sqlExecutor interface {
	ExecContext(context.Context, string, ...any) (sql.Result, error)
	QueryRowContext(context.Context, string, ...any) *sql.Row
}

// OpenStore requires the platform migration; it never creates or repairs schema.
func OpenStore(ctx context.Context, dsn string) (*Store, error) {
	if strings.TrimSpace(dsn) == "" {
		return nil, errors.New("usage database DSN is required")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, fmt.Errorf("open usage database: %w", err)
	}
	db.SetMaxOpenConns(5)
	db.SetMaxIdleConns(2)
	if err := requireSchema(ctx, db); err != nil {
		_ = db.Close()
		return nil, err
	}
	return &Store{db: db}, nil
}

func requireSchema(ctx context.Context, db sqlExecutor) error {
	// Resolve every consumed column as well as the unique identity constraint.
	_, err := db.ExecContext(ctx, `SELECT sequence,event_id,schema_version,source,kind,workspace_id,
		resource_kind,resource_id,incarnation_id,task_id,occurred_at,occurred_at_source,received_at,data
		FROM resource_usage_events WHERE false`)
	if err != nil {
		return fmt.Errorf("usage schema is not migrated; run platform migrations: %w", err)
	}
	var ready bool
	err = db.QueryRowContext(ctx, `SELECT
		EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='resource_usage_events'::regclass
			AND conname='uq_resource_usage_events_identity' AND contype='u')
		AND EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='resource_usage_events'::regclass
			AND tgname='resource_usage_events_append_only' AND tgenabled='O')`).Scan(&ready)
	if err != nil {
		return fmt.Errorf("check usage migration: %w", err)
	}
	if !ready {
		return errors.New("usage schema is not migrated; identity constraint and append-only trigger required")
	}
	return nil
}

func (s *Store) Close() error { return s.db.Close() }

func (s *Store) Record(ctx context.Context, event Event) error {
	if isStorageEvent(event) {
		tx, err := s.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
		if err != nil {
			return err
		}
		defer func() { _ = tx.Rollback() }()
		if err := RecordTx(ctx, tx, event); err != nil {
			return err
		}
		return tx.Commit()
	}
	return recordSQL(ctx, s.db, event)
}

// RecordTx writes within the owner's transaction, never committing it. A caller
// must abort its transition on error so the state and usage fact stay atomic.
func RecordTx(ctx context.Context, tx *sql.Tx, event Event) error {
	if isStorageEvent(event) {
		if _, err := lockStorageScope(ctx, tx, event); err != nil {
			return err
		}
	}
	return recordSQL(ctx, tx, event)
}

func recordSQL(ctx context.Context, db sqlExecutor, event Event) error {
	if err := event.Validate(); err != nil {
		return err
	}
	args := []any{event.ID, event.Source, event.Kind, event.WorkspaceID,
		event.ResourceKind, event.ResourceID, event.IncarnationID, event.TaskID,
		event.OccurredAt.UTC(), event.OccurredAt.UTC().Format(time.RFC3339Nano), string(event.Data), event.SchemaVersion}
	result, err := db.ExecContext(ctx, `INSERT INTO resource_usage_events
		(event_id,source,kind,workspace_id,resource_kind,resource_id,incarnation_id,task_id,occurred_at,occurred_at_source,data,schema_version)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12)
		ON CONFLICT (source,event_id) DO NOTHING`, args...)
	if err != nil {
		return fmt.Errorf("persist usage event %s/%s: %w", event.Source, event.ID, err)
	}
	inserted, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("read usage insert result: %w", err)
	}
	if inserted == 1 {
		return nil
	}
	// A separate statement sees a concurrent winner's committed row under READ
	// COMMITTED. JSONB compares numeric values without decoding through float64.
	var matches bool
	err = db.QueryRowContext(ctx, `SELECT kind=$3 AND workspace_id=$4
		AND resource_kind=$5 AND resource_id=$6 AND incarnation_id=$7 AND task_id=$8
		AND occurred_at=$9 AND occurred_at_source=$10 AND data=$11::jsonb AND schema_version=$12
		FROM resource_usage_events WHERE event_id=$1 AND source=$2`, args...).Scan(&matches)
	if err != nil {
		return fmt.Errorf("compare existing usage event %s/%s: %w", event.Source, event.ID, err)
	}
	if !matches {
		return fmt.Errorf("%w: %s/%s", ErrIdentityCollision, event.Source, event.ID)
	}
	return nil
}
