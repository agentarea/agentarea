package store

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// Partitions is the daily partitions of stream_events (partitions.py). They span every
// workspace, so its methods take a global query runner.
type Partitions struct{}

// PartitionExists reports whether the table name exists.
func (Partitions) PartitionExists(ctx context.Context, q db.Querier, name string) (bool, error) {
	var ok bool
	err := q.QueryRow(ctx, `SELECT to_regclass($1) IS NOT NULL`, pgx.Identifier{name}.Sanitize()).Scan(&ok)
	return ok, err
}

// CreatePartition makes name the partition of day, midnight to midnight UTC.
func (Partitions) CreatePartition(ctx context.Context, q db.Querier, name string, day time.Time) error {
	from := day.UTC().Format(time.DateOnly)
	to := day.UTC().AddDate(0, 0, 1).Format(time.DateOnly)
	_, err := q.Exec(ctx, fmt.Sprintf(
		`CREATE TABLE IF NOT EXISTS %s PARTITION OF stream_events FOR VALUES FROM ('%s 00:00:00+00') TO ('%s 00:00:00+00')`,
		pgx.Identifier{name}.Sanitize(), from, to))
	return err
}

// DropPartition drops name and day's rows of stream_event_counts.
func (Partitions) DropPartition(ctx context.Context, q db.Querier, name string, day time.Time) error {
	if _, err := q.Exec(ctx, `DROP TABLE IF EXISTS `+pgx.Identifier{name}.Sanitize()); err != nil {
		return err
	}
	_, err := q.Exec(ctx, `DELETE FROM stream_event_counts WHERE day = $1::date`, day.UTC().Format(time.DateOnly))
	return err
}

// PartitionNames lists the partitions of stream_events.
func (Partitions) PartitionNames(ctx context.Context, q db.Querier) ([]string, error) {
	rows, err := q.Query(ctx, `SELECT c.relname FROM pg_catalog.pg_inherits i
		JOIN pg_catalog.pg_class c ON c.oid = i.inhrelid
		JOIN pg_catalog.pg_class p ON p.oid = i.inhparent
		WHERE p.relname = 'stream_events'`)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

// EventCursor is the position after the last event of a page of a day.
type EventCursor struct {
	WorkspaceID string
	Sequence    int64
}

// EventsOfDay is up to limit events received on day, ordered by workspace then sequence, after
// cursor (nil for the first page).
func (Partitions) EventsOfDay(ctx context.Context, q db.Querier, day time.Time, after *EventCursor, limit int) ([]domain.RecordedEvent, error) {
	start := time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC)
	ws, seq, first := "", int64(0), true
	if after != nil {
		ws, seq, first = after.WorkspaceID, after.Sequence, false
	}
	rows, err := q.Query(ctx, `SELECT sequence, received_at, stream_id, event_id, event_key, kind, source, subject, occurred_at,
		correlation_id, causation_id, source_id, depth, data, workspace_id, created_by, source_type, session_key, sender,
		attachments, routed_at, subscribers, reacted, skipped, errors
		FROM stream_events
		WHERE received_at >= $1 AND received_at < $2 AND ($3 OR (workspace_id, sequence) > ($4, $5))
		ORDER BY workspace_id, sequence LIMIT $6`, start, start.AddDate(0, 0, 1), first, ws, seq, limit)
	if err != nil {
		return nil, err
	}
	found, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (StreamEvent, error) {
		var i StreamEvent
		err := r.Scan(&i.Sequence, &i.ReceivedAt, &i.StreamID, &i.EventID, &i.EventKey, &i.Kind, &i.Source, &i.Subject,
			&i.OccurredAt, &i.CorrelationID, &i.CausationID, &i.SourceID, &i.Depth, &i.Data, &i.WorkspaceID, &i.CreatedBy,
			&i.SourceType, &i.SessionKey, &i.Sender, &i.Attachments, &i.RoutedAt, &i.Subscribers, &i.Reacted, &i.Skipped, &i.Errors)
		return i, err
	})
	if err != nil {
		return nil, err
	}
	return toRecordedList(found), nil
}
